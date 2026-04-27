import os
import tempfile
from typing import Literal
from uuid import uuid4

import aiofiles
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Security, UploadFile, status
from pydantic import BaseModel

from app.core.logger import get_logger
from app.core.security import require_api_key
from app.graph.workflow import create_graph_thread, get_thread_state, run_pipeline_thread
from app.schemas.extraction import ExtractionOutput
from app.schemas.validation import FieldValidation

log = get_logger(__name__)
router = APIRouter(tags=["Pipeline"])


class SubmitResponse(BaseModel):
    job_id: str


class PipelineResult(BaseModel):
    job_id: str
    status: Literal["processing", "complete"]
    extracted_data: ExtractionOutput | None = None
    validation_results: list[FieldValidation] | None = None
    final_decision: Literal["auto_approve", "flag_for_review", "draft_amendment"] | None = None
    decision_reasoning_or_draft: str | None = None


@router.post(
    "/pipeline/process",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SubmitResponse,
    summary="Submit a trade document for processing",
    description=(
        "Upload a trade document (PDF or image). The pipeline runs asynchronously — "
        "poll `/pipeline/status/{job_id}` for the result."
    ),
)
async def process_pipeline_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Trade document to process (PDF, PNG, JPG, XLS)."),
    _: str = Security(require_api_key),
) -> SubmitResponse:
    log.info(
        "POST /pipeline/process  |  filename=%r  content_type=%r",
        file.filename, file.content_type,
    )

    if not file.filename:
        log.warning("Rejected upload — missing filename")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File upload requires a filename.",
        )

    suffix = os.path.splitext(file.filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        temp_path = tmp.name

    try:
        async with aiofiles.open(temp_path, "wb") as out:
            contents = await file.read()
            await out.write(contents)
        log.info("File saved  |  temp_path=%s  size=%d bytes", temp_path, len(contents))
    except Exception as exc:
        log.exception("Failed to save uploaded file: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    job_id = uuid4().hex
    await create_graph_thread(temp_path, thread_id=job_id)
    log.info("Job created  |  job_id=%s", job_id)

    background_tasks.add_task(run_pipeline_thread, job_id, temp_path)
    log.info("Pipeline background task scheduled  |  job_id=%s", job_id)

    return SubmitResponse(job_id=job_id)


@router.get(
    "/pipeline/status/{job_id}",
    response_model=PipelineResult,
    summary="Poll the status and result of a pipeline job",
    description=(
        "Returns the current state of a pipeline job. "
        "`status` is `processing` while the pipeline is running and `complete` once finished."
    ),
)
async def pipeline_status(
    job_id: str,
    _: str = Security(require_api_key),
) -> PipelineResult:
    log.info("GET /pipeline/status/%s", job_id)
    state = await get_thread_state(job_id)

    if state is None:
        log.warning("Job not found  |  job_id=%s", job_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline job not found.",
        )

    extracted_data = (
        ExtractionOutput.model_validate(state["extracted_data"])
        if state.get("extracted_data")
        else None
    )
    validation_results = (
        [FieldValidation.model_validate(r) for r in state["validation_results"]]
        if state.get("validation_results")
        else None
    )
    job_status: Literal["processing", "complete"] = (
        "complete" if state.get("final_decision") is not None else "processing"
    )

    log.info(
        "Job state returned  |  job_id=%s  status=%s  decision=%s",
        job_id, job_status, state.get("final_decision"),
    )

    return PipelineResult(
        job_id=job_id,
        status=job_status,
        extracted_data=extracted_data,
        validation_results=validation_results,
        final_decision=state.get("final_decision"),
        decision_reasoning_or_draft=state.get("decision_reasoning_or_draft"),
    )
