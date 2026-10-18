from typing import Literal
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class ErrorResponse(BaseModel):
    code: str = Field(..., examples=["VALIDATION_ERROR"])
    message: str
    request_id: str | None = None
    details: dict[str, object] = Field(default_factory=dict)
