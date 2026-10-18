from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.schemas.research import ResearchMode, ResearchRun, ResearchRunCreate, RunStatus

router = APIRouter(prefix="/research", tags=["research"])

# Temporary in-process store for the foundation milestone. Replace with PostgreSQL
# persistence before any multi-worker/deployed use.
_runs: dict[str, ResearchRun] = {}


@router.post("/runs", response_model=ResearchRun, status_code=201)
def create_research_run(payload: ResearchRunCreate) -> ResearchRun:
    run = ResearchRun(
        id=str(uuid4()),
        question=payload.question.strip(),
        mode=payload.mode,
        status=RunStatus.QUEUED,
        created_at=datetime.now(timezone.utc),
        demo=True,
    )
    _runs[run.id] = run
    return run


@router.get("/runs", response_model=list[ResearchRun])
def list_research_runs() -> list[ResearchRun]:
    return sorted(_runs.values(), key=lambda item: item.created_at, reverse=True)


@router.get("/runs/{run_id}", response_model=ResearchRun)
def get_research_run(run_id: str) -> ResearchRun:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    return run
