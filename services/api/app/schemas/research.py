from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class ResearchMode(StrEnum):
    QUICK = "quick"
    DEEP = "deep"
    ACADEMIC = "academic"
    FORENSIC = "forensic"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_LIMITATIONS = "completed_with_limitations"
    FAILED = "failed"


class ResearchRunCreate(BaseModel):
    project_id: str | None = None
    question: str = Field(min_length=8, max_length=2000)
    mode: ResearchMode = ResearchMode.DEEP
    max_sources: int = Field(default=10, ge=1, le=50)
    execute: bool = False


class ResearchRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str | None
    question: str
    mode: ResearchMode
    status: RunStatus
    max_sources: int
    created_at: datetime
    demo: bool = False
    error_message: str | None = None


class ProjectCreate(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    research_question: str = Field(min_length=8, max_length=4000)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    research_question: str
    created_at: datetime
    updated_at: datetime
