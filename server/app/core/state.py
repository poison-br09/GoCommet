from typing import TypedDict


class GraphState(TypedDict):
    raw_document_path: str
    mistral_markdown: str | None
    extracted_data: dict | None
    validation_results: list[dict] | None
    final_decision: str | None
    decision_reasoning_or_draft: str | None
