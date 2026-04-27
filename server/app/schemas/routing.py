from pydantic import BaseModel
from typing import Literal


class RouterDecision(BaseModel):
    decision: Literal["auto_approve", "flag_for_review", "draft_amendment"]
    reasoning: str
    draft_email: str | None = None
