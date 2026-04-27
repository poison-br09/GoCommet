from pydantic import BaseModel
from typing import Literal


class FieldValidation(BaseModel):
    field_name: str
    status: Literal["match", "mismatch", "uncertain"]
    found_value: str | None = None
    expected_value: str | None = None
