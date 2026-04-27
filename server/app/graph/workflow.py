import json
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.extractor_cascade import run_extractor_cascade
from app.agents.router import run_router
from app.agents.validator import run_validator
from app.core.logger import get_logger
from app.core.state import GraphState
from app.db.database import load_graph_thread_state, save_graph_thread_state
from app.schemas.extraction import ExtractionOutput
from app.schemas.validation import FieldValidation

log = get_logger(__name__)
_workflow: Any | None = None


async def persist_thread_state(thread_id: str, state: GraphState) -> None:
    await save_graph_thread_state(thread_id, state)


async def get_thread_state(thread_id: str) -> GraphState | None:
    return await load_graph_thread_state(thread_id)


async def extract_node(state: GraphState) -> dict[str, Any]:
    log.info("extract_node  START  |  document=%s", state["raw_document_path"])
    mistral_markdown, extracted_data = await run_extractor_cascade(state["raw_document_path"])
    result = {
        "mistral_markdown": mistral_markdown,
        "extracted_data": extracted_data.model_dump(),
    }
    line_items = extracted_data.line_items or []
    log.info(
        "extract_node  DONE   |  markdown_chars=%d  line_items=%d  extracted=%s",
        len(mistral_markdown),
        len(line_items),
        json.dumps(extracted_data.model_dump(), default=str),
    )
    return result


async def validate_node(state: GraphState) -> dict[str, Any]:
    if state["extracted_data"] is None:
        raise ValueError("Cannot validate before extraction is complete")

    log.info("validate_node  START  |  extracted_data=%s", json.dumps(state["extracted_data"], default=str))
    extraction = ExtractionOutput.model_validate(state["extracted_data"])
    validation_results = await run_validator(extraction)
    result = {"validation_results": [item.model_dump() for item in validation_results]}
    log.info(
        "validate_node  DONE   |  results=%s",
        json.dumps(result["validation_results"], default=str),
    )
    return result


async def route_node(state: GraphState) -> dict[str, Any]:
    if state["validation_results"] is None:
        raise ValueError("Cannot route before validation is complete")

    log.info("route_node  START  |  validation_results=%s", json.dumps(state["validation_results"], default=str))
    validation_results = [
        FieldValidation.model_validate(item) for item in state["validation_results"]
    ]
    routing_decision = await run_router(validation_results)
    result = {
        "final_decision": routing_decision.decision,
        "decision_reasoning_or_draft": (
            routing_decision.draft_email or routing_decision.reasoning
        ),
    }
    log.info(
        "route_node  DONE   |  decision=%s  reasoning=%r",
        routing_decision.decision,
        routing_decision.reasoning,
    )
    return result


async def initialize_langgraph_workflow() -> Any:
    global _workflow
    if _workflow is not None:
        return _workflow

    graph = StateGraph(GraphState)
    graph.add_node("extract", extract_node)
    graph.add_node("validate", validate_node)
    graph.add_node("route", route_node)

    graph.add_edge(START, "extract")
    graph.add_edge("extract", "validate")
    graph.add_edge("validate", "route")
    graph.add_edge("route", END)

    _workflow = graph.compile(checkpointer=MemorySaver())
    return _workflow


async def run_pipeline_thread(thread_id: str, raw_document_path: str) -> GraphState:
    log.info("pipeline  START  |  thread_id=%s  document=%s", thread_id, raw_document_path)
    state: GraphState = {
        "raw_document_path": raw_document_path,
        "mistral_markdown": None,
        "extracted_data": None,
        "validation_results": None,
        "final_decision": None,
        "decision_reasoning_or_draft": None,
    }
    workflow = await initialize_langgraph_workflow()
    graph_config = {"configurable": {"thread_id": thread_id}}
    final_state = state

    async for graph_state in workflow.astream(
        state,
        config=graph_config,
        stream_mode="values",
    ):
        final_state = graph_state
        await persist_thread_state(thread_id, final_state)
        log.debug("pipeline  STATE_SAVED  |  thread_id=%s  decision=%s", thread_id, final_state.get("final_decision"))

    log.info(
        "pipeline  DONE   |  thread_id=%s  decision=%s",
        thread_id, final_state.get("final_decision"),
    )
    return final_state


async def create_graph_thread(raw_document_path: str, thread_id: str | None = None) -> str:
    thread_id = thread_id or uuid4().hex
    log.info("create_graph_thread  |  thread_id=%s  document=%s", thread_id, raw_document_path)
    await persist_thread_state(thread_id, {
        "raw_document_path": raw_document_path,
        "mistral_markdown": None,
        "extracted_data": None,
        "validation_results": None,
        "final_decision": None,
        "decision_reasoning_or_draft": None,
    })
    return thread_id
