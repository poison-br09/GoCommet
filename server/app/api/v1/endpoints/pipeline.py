import asyncio
import json
import os
import secrets
import tempfile
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

import aiofiles
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, Request, Security, UploadFile, status
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.core.logger import get_logger
from app.core.security import require_api_key
from app.graph.workflow import (
    create_graph_thread,
    get_pending_review_threads,
    get_review_queue_threads,
    get_thread_state,
    resume_pipeline_thread,
    run_email_pipeline_thread,
)
from app.schemas.events import EmailPayload, ResumePipelineRequest

log = get_logger(__name__)
router = APIRouter(tags=["Pipeline"])


PipelineStatus = Literal["processing", "pending_review", "sent", "complete", "failed"]


class SubmitResponse(BaseModel):
    job_id: str


class WebhookResponse(BaseModel):
    thread_id: str


class PipelineResult(BaseModel):
    job_id: str
    thread_id: str
    status: PipelineStatus
    incoming_email: dict[str, Any] | None = None
    extracted_data: Any | None = None
    validation_results: list[dict[str, Any]] | None = None
    final_decision: Literal["auto_approve", "flag_for_review", "draft_amendment"] | None = None
    decision_reasoning_or_draft: str | None = None
    human_review_status: str | None = None
    edited_email_text: str | None = None
    mock_send_result: dict[str, Any] | None = None
    error_message: str | None = None


class PendingReviewItem(BaseModel):
    thread_id: str
    updated_at: datetime
    status: PipelineStatus | None = None
    incoming_email: dict[str, Any] | None = None
    final_decision: str | None = None
    decision_reasoning_or_draft: str | None = None
    validation_results: list[dict[str, Any]] | None = None
    error_message: str | None = None


def _status_from_state(state: dict[str, Any]) -> PipelineStatus:
    review_status = state.get("human_review_status")
    if review_status == "failed":
        return "failed"
    if review_status == "sent":
        return "sent"
    if review_status == "pending":
        return "pending_review"
    if state.get("final_decision") is not None:
        return "complete"
    return "processing"


def _to_pipeline_result(thread_id: str, state: dict[str, Any]) -> PipelineResult:
    return PipelineResult(
        job_id=thread_id,
        thread_id=thread_id,
        status=_status_from_state(state),
        incoming_email=state.get("incoming_email"),
        extracted_data=state.get("extracted_data"),
        validation_results=state.get("validation_results"),
        final_decision=state.get("final_decision"),
        decision_reasoning_or_draft=state.get("decision_reasoning_or_draft"),
        human_review_status=state.get("human_review_status"),
        edited_email_text=state.get("edited_email_text"),
        mock_send_result=state.get("mock_send_result"),
        error_message=state.get("error_message"),
    )


def _review_queue_item(record: dict[str, Any]) -> PendingReviewItem:
    return PendingReviewItem(
        thread_id=record["thread_id"],
        updated_at=record["updated_at"],
        status=_status_from_state(record["state"]),
        incoming_email=record["state"].get("incoming_email"),
        final_decision=record["state"].get("final_decision"),
        decision_reasoning_or_draft=record["state"].get("decision_reasoning_or_draft"),
        validation_results=record["state"].get("validation_results"),
        error_message=record["state"].get("error_message"),
    )


def _assert_stream_api_key(api_key: str) -> None:
    expected = settings.api_key.get_secret_value()
    if not secrets.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


@router.post(
    "/webhook/incoming-email",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WebhookResponse,
    summary="Trigger the pipeline from a normalized inbound email event",
)
async def incoming_email_webhook(
    payload: EmailPayload,
    background_tasks: BackgroundTasks,
    _: str = Security(require_api_key),
) -> WebhookResponse:
    missing_paths = [path for path in payload.attachment_paths if not os.path.isfile(path)]
    if missing_paths:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Attachment path(s) not found: {', '.join(missing_paths)}",
        )

    thread_id = await create_graph_thread(payload)
    background_tasks.add_task(run_email_pipeline_thread, thread_id, payload)
    log.info(
        "Webhook email accepted  |  thread_id=%s  subject=%r  attachments=%d",
        thread_id,
        payload.subject,
        len(payload.attachment_paths),
    )
    return WebhookResponse(thread_id=thread_id)


@router.post(
    "/pipeline/process",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SubmitResponse,
    summary="Submit trade documents for processing",
    description=(
        "API-only compatibility endpoint for manual multipart uploads. Uploaded files "
        "are wrapped as one multi-attachment email event and follow the same "
        "human-review pipeline."
    ),
)
async def process_pipeline_files(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(..., description="Trade documents to process (PDF, PNG, JPG, XLS)."),
    _: str = Security(require_api_key),
) -> SubmitResponse:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file is required.",
        )

    temp_paths: list[str] = []
    original_names: list[str] = []
    for file in files:
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Every uploaded file requires a filename.",
            )

        suffix = os.path.splitext(file.filename)[1] or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = tmp.name

        try:
            async with aiofiles.open(temp_path, "wb") as out:
                contents = await file.read()
                await out.write(contents)
            temp_paths.append(temp_path)
            original_names.append(file.filename)
            log.info("File saved  |  filename=%r  temp_path=%s  size=%d bytes", file.filename, temp_path, len(contents))
        except Exception as exc:
            log.exception("Failed to save uploaded file %r: %s", file.filename, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            )

    payload = EmailPayload(
        sender="manual-upload@gocomet.local",
        subject=f"Manual upload: {len(temp_paths)} file(s) - {', '.join(original_names)}",
        attachment_paths=temp_paths,
    )
    job_id = uuid4().hex
    await create_graph_thread(payload, thread_id=job_id)
    background_tasks.add_task(run_email_pipeline_thread, job_id, payload)
    return SubmitResponse(job_id=job_id)


@router.get(
    "/pipeline/status/{job_id}",
    response_model=PipelineResult,
    summary="Poll the status and result of a pipeline job",
)
async def pipeline_status(
    job_id: str,
    _: str = Security(require_api_key),
) -> PipelineResult:
    state = await get_thread_state(job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline job not found.",
        )
    return _to_pipeline_result(job_id, state)


@router.get(
    "/pipeline/pending-review",
    response_model=list[PendingReviewItem],
    summary="List LangGraph threads paused for CG review",
)
async def pending_review(
    _: str = Security(require_api_key),
) -> list[PendingReviewItem]:
    records = await get_pending_review_threads()
    return [_review_queue_item(record) for record in records]


@router.get(
    "/pipeline/review-queue",
    response_model=list[PendingReviewItem],
    summary="List incoming, failed, and paused threads for the CG workflow",
)
async def review_queue(
    _: str = Security(require_api_key),
) -> list[PendingReviewItem]:
    records = await get_review_queue_threads()
    return [_review_queue_item(record) for record in records]


@router.get(
    "/pipeline/review-queue/stream",
    summary="Stream incoming and review queue updates to the CG UI",
)
async def review_queue_stream(
    request: Request,
    api_key: str = Query(...),
) -> StreamingResponse:
    _assert_stream_api_key(api_key)

    async def event_stream():
        last_payload: str | None = None
        while not await request.is_disconnected():
            records = await get_review_queue_threads()
            items = [_review_queue_item(record).model_dump(mode="json") for record in records]
            payload = json.dumps(items, default=str)
            if payload != last_payload:
                yield f"event: queue\ndata: {payload}\n\n"
                last_payload = payload
            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/pipeline/resume/{thread_id}",
    response_model=PipelineResult,
    summary="Resume a paused pipeline after CG approval",
)
async def resume_pipeline(
    thread_id: str,
    body: ResumePipelineRequest,
    _: str = Security(require_api_key),
) -> PipelineResult:
    state = await get_thread_state(thread_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline thread not found.",
        )
    if state.get("human_review_status") not in {"pending", "approved"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Pipeline thread is not pending review; current status is {state.get('human_review_status')}.",
        )

    try:
        final_state = await resume_pipeline_thread(thread_id, body.edited_email_text)
    except Exception as exc:
        log.exception("Pipeline resume failed  |  thread_id=%s  error=%s", thread_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    return _to_pipeline_result(thread_id, final_state)
