from pydantic import BaseModel, Field


class EmailPayload(BaseModel):
    sender: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    attachment_paths: list[str] = Field(..., min_length=1)


class ResumePipelineRequest(BaseModel):
    edited_email_text: str = Field(..., min_length=1)
