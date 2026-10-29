from datetime import datetime
from enum import StrEnum
from typing import Literal
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
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class ResearchRunCreate(BaseModel):
    project_id: str | None = None
    question: str = Field(min_length=8, max_length=2000)
    mode: ResearchMode = ResearchMode.DEEP
    max_sources: int = Field(default=10, ge=1, le=50)
    source_paper_ids: list[str] = Field(default_factory=list, max_length=5)
    execute: bool = False
    # Optional controlled-experiment arm. Omitted for normal use (full lifecycle / D).
    evaluation_arm: Literal["A", "B", "C", "D"] | None = None


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
    cancel_requested_at: datetime | None = None
    cancelled_at: datetime | None = None
    retry_of_run_id: str | None = None


class ProjectCreate(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    research_question: str = Field(min_length=8, max_length=4000)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=240)
    research_question: str | None = Field(default=None, min_length=8, max_length=4000)
    archived: bool | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    research_question: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
