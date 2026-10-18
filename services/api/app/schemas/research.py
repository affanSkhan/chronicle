from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field


class ResearchMode(StrEnum):
    QUICK = "quick"
    DEEP = "deep"
    ACADEMIC = "academic"
    FORENSIC = "forensic"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ResearchRunCreate(BaseModel):
    question: str = Field(min_length=8, max_length=2000)
    mode: ResearchMode = ResearchMode.DEEP
    max_sources: int = Field(default=10, ge=1, le=50)


class ResearchRun(BaseModel):
    id: str
    question: str
    mode: ResearchMode
    status: RunStatus
    created_at: datetime
    demo: bool = False
