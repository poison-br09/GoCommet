from typing import Any, TypedDict


class GraphState(TypedDict):
    thread_id: str
    incoming_email: dict[str, Any]
    mistral_markdown: list[dict[str, Any]] | None
    extracted_data: list[dict[str, Any]] | None
    validation_results: list[dict] | None
    final_decision: str | None
    decision_reasoning_or_draft: str | None
    human_review_status: str
    edited_email_text: str | None
    mock_send_result: dict[str, Any] | None
    error_message: str | None
