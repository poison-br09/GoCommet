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
    save_graph_thread_state,
)
from app.schemas.events import EmailPayload
from app.schemas.extraction import ExtractionOutput
from app.schemas.validation import FieldValidation

log = get_logger(__name__)
_workflow: Any | None = None

CRITICAL_CROSS_DOC_FIELDS = ("hs_code", "consignee_name")


def _initial_state(incoming_email: EmailPayload) -> GraphState:
    return {
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
    queue_statuses = {"processing", "pending", "failed"}
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


async def route_node(state: GraphState) -> dict[str, Any]:
    if state["validation_results"] is None:
        raise ValueError("Cannot route before validation is complete")

    validation_results = [
        FieldValidation.model_validate(item) for item in state["validation_results"]
    ]
    routing_decision = await run_router(validation_results)
    draft_or_reasoning = routing_decision.draft_email or routing_decision.reasoning
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
    incoming_email = state["incoming_email"]
    approved_text = state.get("edited_email_text") or state.get("decision_reasoning_or_draft")
    if not approved_text:
        raise ValueError("Cannot send without approved email text")

    mock_send_result = {
        "to": incoming_email.get("sender"),
        "subject": f"Re: {incoming_email.get('subject')}",
        "body": approved_text,
        "status": "sent",
    }
    log.info(
        "send_email_node  MOCK_SENT  |  to=%s  subject=%r",
        mock_send_result["to"],
        mock_send_result["subject"],
    )
    return {
        "human_review_status": "sent",
        "mock_send_result": mock_send_result,
    }


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
    state = _initial_state(incoming_email)
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
    persisted = await get_thread_state(thread_id)
    if persisted is None:
        raise ValueError(f"Pipeline thread not found: {thread_id}")

    workflow = await initialize_langgraph_workflow()
    graph_config = {"configurable": {"thread_id": thread_id}}
    try:
        await workflow.aupdate_state(
            graph_config,
            {
                "edited_email_text": edited_email_text,
                "human_review_status": "approved",
            },
            as_node="route",
        )
    except Exception as exc:
        log.warning(
            "resume_pipeline_thread  CHECKPOINT_MISSING  |  thread_id=%s  falling back to persisted state: %s",
            thread_id,
            exc,
        )
        approved_state: GraphState = {
            **persisted,
            "edited_email_text": edited_email_text,
            "human_review_status": "approved",
        }
        final_state: GraphState = {
            **approved_state,
            **await send_email_node(approved_state),
        }
        await persist_thread_state(thread_id, final_state)
        return final_state

    final_state: GraphState | None = None
    async for graph_state in workflow.astream(
        None,
        config=graph_config,
        stream_mode="values",
    ):
        final_state = graph_state
        await persist_thread_state(thread_id, final_state)

    if final_state is None:
        final_state = persisted

    await persist_thread_state(thread_id, final_state)
    return final_state


async def create_graph_thread(incoming_email: EmailPayload, thread_id: str | None = None) -> str:
    thread_id = thread_id or uuid4().hex
    log.info("create_graph_thread  |  thread_id=%s  subject=%r", thread_id, incoming_email.subject)
    await persist_thread_state(thread_id, _initial_state(incoming_email))
    return thread_id


async def run_pipeline_thread(thread_id: str, raw_document_path: str) -> GraphState:
    incoming_email = EmailPayload(
        sender="manual-upload@gocomet.local",
        subject=f"Manual upload: {Path(raw_document_path).name}",
        attachment_paths=[raw_document_path],
    )
    return await run_email_pipeline_thread(thread_id, incoming_email)
