import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.extractor_cascade import run_extractor_cascade
from app.agents.router import run_router
from app.agents.validator import run_validator
from app.core.logger import get_logger
from app.core.state import GraphState
from app.db.database import (
    list_graph_thread_states,
    load_graph_thread_state,
    save_email_audit_record,
    save_graph_thread_state,
)
from app.ingestion.outbound_email import (
    normalize_recipient,
    smtp_configuration_status,
    send_review_email,
    smtp_is_configured,
    split_subject_and_body,
)
from app.schemas.events import EmailPayload
from app.schemas.extraction import ExtractionOutput
from app.schemas.validation import FieldValidation

log = get_logger(__name__)
_workflow: Any | None = None
_resume_locks: dict[str, asyncio.Lock] = {}

CRITICAL_CROSS_DOC_FIELDS = ("hs_code", "consignee_name")


def _initial_state(incoming_email: EmailPayload, thread_id: str) -> GraphState:
    return {
        "thread_id": thread_id,
        "incoming_email": incoming_email.model_dump(),
        "mistral_markdown": None,
        "extracted_data": None,
        "validation_results": None,
        "final_decision": None,
        "decision_reasoning_or_draft": None,
        "human_review_status": "processing",
        "edited_email_text": None,
        "mock_send_result": None,
        "error_message": None,
    }


async def persist_thread_state(thread_id: str, state: GraphState) -> None:
    await save_graph_thread_state(thread_id, state)


async def get_thread_state(thread_id: str) -> GraphState | None:
    return await load_graph_thread_state(thread_id)


async def get_pending_review_threads() -> list[dict[str, Any]]:
    records = await list_graph_thread_states()
    return [
        {
            "thread_id": record["thread_id"],
            "updated_at": record["updated_at"],
            "state": record["state"],
        }
        for record in records
        if record["state"].get("human_review_status") == "pending"
    ]


async def get_review_queue_threads() -> list[dict[str, Any]]:
    records = await list_graph_thread_states()
    queue_statuses = {"processing", "pending", "failed", "sent"}
    return [
        {
            "thread_id": record["thread_id"],
            "updated_at": record["updated_at"],
            "state": record["state"],
        }
        for record in records
        if record["state"].get("human_review_status") in queue_statuses
    ]


def _field_value(extraction: dict[str, Any], field_name: str) -> str | None:
    field = extraction.get(field_name)
    if isinstance(field, dict):
        value = field.get("value")
        return str(value).strip() if value is not None and str(value).strip() else None
    return None


def _field_confidence(extraction: dict[str, Any], field_name: str) -> float | None:
    field = extraction.get(field_name)
    if isinstance(field, dict):
        confidence = field.get("confidence")
        if isinstance(confidence, int | float):
            return float(confidence)
    return None


def _source_snippet(markdown: str, value: str | None) -> str | None:
    if not markdown:
        return None
    compact_markdown = " ".join(markdown.split())
    if not value:
        return compact_markdown[:220] if compact_markdown else None

    needle = value.strip()
    index = compact_markdown.lower().find(needle.lower())
    if index == -1:
        return compact_markdown[:220] if compact_markdown else None

    start = max(index - 80, 0)
    end = min(index + len(needle) + 120, len(compact_markdown))
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(compact_markdown) else ""
    return f"{prefix}{compact_markdown[start:end]}{suffix}"


async def _extract_one(path: str) -> dict[str, Any]:
    log.info("extract_one  START  |  document=%s", path)
    mistral_markdown, extracted_data = await run_extractor_cascade(path)
    document_name = Path(path).name
    result = {
        "path": path,
        "document_name": document_name,
        "markdown": mistral_markdown,
        "extracted_data": extracted_data.model_dump(),
    }
    log.info(
        "extract_one  DONE   |  document=%s  markdown_chars=%d  extracted=%s",
        document_name,
        len(mistral_markdown),
        json.dumps(result["extracted_data"], default=str),
    )
    return result


async def extract_node(state: GraphState) -> dict[str, Any]:
    incoming_email = EmailPayload.model_validate(state["incoming_email"])
    attachment_paths = incoming_email.attachment_paths
    log.info(
        "extract_node  START  |  subject=%r  attachments=%d",
        incoming_email.subject,
        len(attachment_paths),
    )

    extracted_documents = await asyncio.gather(
        *(_extract_one(path) for path in attachment_paths)
    )
    return {
        "mistral_markdown": [
            {
                "document_name": doc["document_name"],
                "path": doc["path"],
                "markdown": doc["markdown"],
            }
            for doc in extracted_documents
        ],
        "extracted_data": [
            {
                "document_name": doc["document_name"],
                "path": doc["path"],
                **doc["extracted_data"],
            }
            for doc in extracted_documents
        ],
    }


async def cross_document_validate_node(state: GraphState) -> dict[str, Any]:
    extracted_data = state.get("extracted_data") or []
    if len(extracted_data) < 2:
        log.info(
            "cross_document_validate_node  SKIP  |  attachments=%d  reason=needs_at_least_two_documents",
            len(extracted_data),
        )
        return {"validation_results": []}

    markdown_by_path = {
        item["path"]: item.get("markdown", "")
        for item in (state.get("mistral_markdown") or [])
    }
    results: list[dict[str, Any]] = []

    for field_name in CRITICAL_CROSS_DOC_FIELDS:
        observed = [
            {
                "document_name": item.get("document_name") or Path(item.get("path", "")).name,
                "path": item.get("path"),
                "value": _field_value(item, field_name),
                "confidence": _field_confidence(item, field_name),
                "snippet": _source_snippet(
                    markdown_by_path.get(item.get("path"), ""),
                    _field_value(item, field_name),
                ),
            }
            for item in extracted_data
        ]
        present_values = [item["value"] for item in observed if item["value"]]

        expected_value = present_values[0] if present_values else None

        for item in observed:
            if not item["value"]:
                status = "uncertain"
            elif item["value"] == expected_value:
                status = "match"
            else:
                status = "mismatch"

            results.append({
                "field_name": field_name,
                "status": status,
                "found_value": item["value"],
                "expected_value": expected_value,
                "document_name": item["document_name"],
                "source_snippet": item["snippet"],
                "confidence": item["confidence"],
                "validation_type": "cross_document",
            })

    log.info(
        "cross_document_validate_node  DONE  |  results=%s",
        json.dumps(results, default=str),
    )
    return {"validation_results": results}


async def validate_node(state: GraphState) -> dict[str, Any]:
    extracted_data = state.get("extracted_data") or []
    validation_results = list(state.get("validation_results") or [])

    for item in extracted_data:
        document_name = item.get("document_name")
        path = item.get("path")
        extraction_payload = {
            key: value
            for key, value in item.items()
            if key not in {"document_name", "path"}
        }
        extraction = ExtractionOutput.model_validate(extraction_payload)
        document_results = await run_validator(extraction)
        for result in document_results:
            row = result.model_dump()
            row["document_name"] = document_name
            field_data = extraction_payload.get(row.get("field_name"))
            if isinstance(field_data, dict):
                row["confidence"] = field_data.get("confidence")
            row["source_snippet"] = _source_snippet(
                next(
                    (
                        md.get("markdown", "")
                        for md in (state.get("mistral_markdown") or [])
                        if md.get("path") == path
                    ),
                    "",
                ),
                row.get("found_value"),
            )
            row["validation_type"] = "customer_rules"
            validation_results.append(row)

    log.info(
        "validate_node  DONE   |  results=%s",
        json.dumps(validation_results, default=str),
    )
    return {"validation_results": validation_results}


def _approval_email(state: GraphState) -> str:
    incoming_email = state["incoming_email"]
    subject = incoming_email.get("subject", "submitted shipment documents")
    return (
        f"Subject: Approved - {subject}\n\n"
        "Dear Shipping Unit,\n\n"
        "We have reviewed the submitted shipment document set and the validation checks are clear. "
        "The documents are approved for onward processing.\n\n"
        "Thank you,\n"
        "GoComet Trade Compliance Team"
    )


def _draft_email_from_state(state: GraphState) -> str:
    validation_results = state.get("validation_results") or []
    flagged = [item for item in validation_results if item.get("status") != "match"]
    if not flagged:
        return _approval_email(state)

    lines = [
        "Subject: Amendment Request - Shipping Document Discrepancy",
        "",
        "Dear Shipping Unit,",
        "",
        "We have reviewed the submitted shipping document set and identified the following items that require correction or confirmation before approval:",
    ]
    for item in flagged:
        document = item.get("document_name") or "document"
        field_name = item.get("field_name") or "field"
        found = item.get("found_value") or "-"
        expected = item.get("expected_value") or "-"
        status = item.get("status") or "review"
        lines.append(f'  - {document}: {field_name} ({status}) - found "{found}"; expected "{expected}"')
    lines.extend([
        "",
        "Please issue corrected documents or confirm the uncertain values at your earliest convenience.",
        "",
        "Thank you for your prompt attention to this matter.",
        "",
        "GoComet Trade Compliance Team",
    ])
    return "\n".join(lines)


async def route_node(state: GraphState) -> dict[str, Any]:
    if state["validation_results"] is None:
        raise ValueError("Cannot route before validation is complete")

    validation_results = [
        FieldValidation.model_validate(item) for item in state["validation_results"]
    ]
    routing_decision = await run_router(validation_results)
    draft_or_reasoning = routing_decision.draft_email or _draft_email_from_state(state)
    if routing_decision.decision == "auto_approve":
        draft_or_reasoning = _approval_email(state)

    result = {
        "final_decision": routing_decision.decision,
        "decision_reasoning_or_draft": draft_or_reasoning,
        "human_review_status": "pending",
    }
    log.info(
        "route_node  DONE   |  decision=%s  human_review_status=pending",
        routing_decision.decision,
    )
    return result


async def send_email_node(state: GraphState) -> dict[str, Any]:
    thread_id = state.get("thread_id")
    incoming_email = state.get("incoming_email") or {
        "sender": "shipping.unit@example.com",
        "subject": "Shipment documents",
        "attachment_paths": [],
    }
    approved_text = state.get("edited_email_text") or state.get("decision_reasoning_or_draft")
    if not approved_text:
        raise ValueError("Cannot send without approved email text")

    default_subject = f"Re: {incoming_email.get('subject') or 'Shipment documents'}"
    subject, body = split_subject_and_body(default_subject, approved_text)
    raw_to_address = incoming_email.get("sender") or "shipping.unit@example.com"
    send_result = {
        "to": raw_to_address,
        "subject": subject,
        "body": body,
        "status": "sent",
        "delivery": "mock",
    }
    if smtp_is_configured():
        to_address = normalize_recipient(raw_to_address)
        send_result.update(await send_review_email(to_address, subject, body))
        send_result["to"] = to_address
    else:
        log.warning(
            "send_email_node  SMTP_NOT_USED  |  reason=%s",
            smtp_configuration_status(),
        )

    log.info(
        "send_email_node  SENT  |  delivery=%s  to=%s  subject=%r",
        send_result["delivery"],
        send_result["to"],
        send_result["subject"],
    )
    result = {
        "human_review_status": "sent",
        "mock_send_result": send_result,
    }
    if thread_id:
        await persist_thread_state(thread_id, {**state, **result})

    if thread_id:
        attachment_paths = incoming_email.get("attachment_paths") or []
        await save_email_audit_record(
            thread_id=thread_id,
            incoming_sender=incoming_email.get("sender"),
            incoming_subject=incoming_email.get("subject"),
            attachment_file_names=[Path(path).name for path in attachment_paths],
            attachment_paths=attachment_paths,
            final_decision=state.get("final_decision"),
            human_review_status="sent",
            validation_results=state.get("validation_results"),
            outgoing_to=send_result.get("to"),
            outgoing_subject=send_result.get("subject"),
            outgoing_body=send_result.get("body"),
            delivery=send_result.get("delivery"),
            send_status=send_result.get("status"),
            message_id=send_result.get("message_id"),
            sent_at=send_result.get("sent_at"),
        )
    return result


async def initialize_langgraph_workflow() -> Any:
    global _workflow
    if _workflow is not None:
        return _workflow

    graph = StateGraph(GraphState)
    graph.add_node("extract", extract_node)
    graph.add_node("cross_document_validate", cross_document_validate_node)
    graph.add_node("validate", validate_node)
    graph.add_node("route", route_node)
    graph.add_node("send_email_node", send_email_node)

    graph.add_edge(START, "extract")
    graph.add_edge("extract", "cross_document_validate")
    graph.add_edge("cross_document_validate", "validate")
    graph.add_edge("validate", "route")
    graph.add_edge("route", "send_email_node")
    graph.add_edge("send_email_node", END)

    _workflow = graph.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["send_email_node"],
    )
    return _workflow


async def run_email_pipeline_thread(thread_id: str, incoming_email: EmailPayload) -> GraphState:
    log.info(
        "pipeline  START  |  thread_id=%s  subject=%r",
        thread_id,
        incoming_email.subject,
    )
    state = _initial_state(incoming_email, thread_id)
    workflow = await initialize_langgraph_workflow()
    graph_config = {"configurable": {"thread_id": thread_id}}
    final_state = state

    try:
        async for graph_state in workflow.astream(
            state,
            config=graph_config,
            stream_mode="values",
        ):
            final_state = graph_state
            await persist_thread_state(thread_id, final_state)
            log.debug(
                "pipeline  STATE_SAVED  |  thread_id=%s  review=%s  decision=%s",
                thread_id,
                final_state.get("human_review_status"),
                final_state.get("final_decision"),
            )
    except Exception as exc:
        final_state = {
            **final_state,
            "human_review_status": "failed",
            "error_message": str(exc),
        }
        await persist_thread_state(thread_id, final_state)
        log.exception(
            "pipeline  FAILED  |  thread_id=%s  error=%s",
            thread_id,
            exc,
        )
        return final_state

    await persist_thread_state(thread_id, final_state)
    log.info(
        "pipeline  PAUSED_OR_DONE  |  thread_id=%s  review=%s  decision=%s",
        thread_id,
        final_state.get("human_review_status"),
        final_state.get("final_decision"),
    )
    return final_state


async def resume_pipeline_thread(thread_id: str, edited_email_text: str) -> GraphState:
    lock = _resume_locks.setdefault(thread_id, asyncio.Lock())
    async with lock:
        persisted = await get_thread_state(thread_id)
        if persisted is None:
            raise ValueError(f"Pipeline thread not found: {thread_id}")
        if persisted.get("human_review_status") == "sent":
            log.info("resume_pipeline_thread  ALREADY_SENT  |  thread_id=%s", thread_id)
            return persisted

        approved_state: GraphState = {
            **persisted,
            "thread_id": thread_id,
            "edited_email_text": edited_email_text,
            "human_review_status": "approved",
        }
        await persist_thread_state(thread_id, approved_state)

        workflow = await initialize_langgraph_workflow()
        graph_config = {"configurable": {"thread_id": thread_id}}
        try:
            await workflow.aupdate_state(
                graph_config,
                approved_state,
                as_node="route",
            )
            final_state: GraphState | None = None
            async for graph_state in workflow.astream(
                None,
                config=graph_config,
                stream_mode="values",
            ):
                final_state = {
                    **approved_state,
                    **graph_state,
                }
                await persist_thread_state(thread_id, final_state)
        except Exception as exc:
            log.warning(
                "resume_pipeline_thread  CHECKPOINT_RESUME_FAILED  |  thread_id=%s  falling back to persisted state: %s",
                thread_id,
                exc,
            )
            final_state = None

        latest = await get_thread_state(thread_id)
        if latest and latest.get("human_review_status") == "sent":
            return latest

        if final_state is None:
            final_state = {
                **approved_state,
                **await send_email_node(approved_state),
            }

        await persist_thread_state(thread_id, final_state)
        return final_state


async def create_graph_thread(incoming_email: EmailPayload, thread_id: str | None = None) -> str:
    thread_id = thread_id or uuid4().hex
    log.info("create_graph_thread  |  thread_id=%s  subject=%r", thread_id, incoming_email.subject)
    await persist_thread_state(thread_id, _initial_state(incoming_email, thread_id))
    return thread_id


async def run_pipeline_thread(thread_id: str, raw_document_path: str) -> GraphState:
    incoming_email = EmailPayload(
        sender="manual-upload@gocomet.local",
        subject=f"Manual upload: {Path(raw_document_path).name}",
        attachment_paths=[raw_document_path],
    )
    return await run_email_pipeline_thread(thread_id, incoming_email)
