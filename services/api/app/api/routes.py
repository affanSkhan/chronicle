from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import ResearchProject, ResearchRun, User
from app.schemas.research import ProjectCreate, ProjectRead, ResearchRun as ResearchRunSchema, ResearchRunCreate
from app.services.audit import record_audit_event
from app.services.research_pipeline import execute_research_run
from app.services.research_planner import build_research_plan

router = APIRouter(tags=["research"], dependencies=[Depends(get_current_user)])


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ResearchProject:
    project = ResearchProject(owner_user_id=current_user.id, title=payload.title.strip(), research_question=payload.research_question.strip())
    db.add(project)
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=None,
        target_entity_type="research_project",
        target_entity_id=project.id,
        action="research_project.created",
        previous_value=None,
        new_value={"title": project.title, "research_question": project.research_question},
        reason="Research workspace created.",
    )
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[ResearchProject]:
    return list(db.scalars(select(ResearchProject).where(ResearchProject.owner_user_id == current_user.id).order_by(ResearchProject.updated_at.desc())).all())


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ResearchProject:
    project = db.scalar(select(ResearchProject).where(ResearchProject.id == project_id, ResearchProject.owner_user_id == current_user.id))
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found.")
    return project


@router.post("/research/runs", response_model=ResearchRunSchema, status_code=201)
def create_research_run(payload: ResearchRunCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ResearchRun:
    if payload.project_id and db.scalar(select(ResearchProject.id).where(ResearchProject.id == payload.project_id, ResearchProject.owner_user_id == current_user.id)) is None:
        raise HTTPException(status_code=404, detail="Research project not found.")
    run = ResearchRun(
        owner_user_id=current_user.id,
        project_id=payload.project_id,
        question=payload.question.strip(),
        mode=payload.mode.value,
        status="queued",
        max_sources=payload.max_sources,
        demo=not payload.execute,
        configuration={
            "pipeline": "mode-aware-scholarly-discovery" if payload.execute else "request-only-demo",
            "max_sources": payload.max_sources,
            "research_plan": build_research_plan(payload.question.strip(), payload.mode.value, payload.max_sources),
        },
    )
    db.add(run)
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=run.id,
        target_entity_type="research_run",
        target_entity_id=run.id,
        action="research_run.created",
        previous_value=None,
        new_value={
            "question": run.question,
            "mode": run.mode,
            "status": run.status,
            "max_sources": run.max_sources,
            "execute": payload.execute,
        },
        reason="Research run submitted.",
    )
    db.commit()
    db.refresh(run)
    if payload.execute:
        background_tasks.add_task(execute_research_run, run.id)
    return run


@router.get("/research/runs", response_model=list[ResearchRunSchema])
def list_research_runs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[ResearchRun]:
    return list(db.scalars(select(ResearchRun).where(ResearchRun.owner_user_id == current_user.id).order_by(ResearchRun.created_at.desc()).limit(100)).all())


@router.get("/research/runs/{run_id}", response_model=ResearchRunSchema)
def get_research_run(run_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ResearchRun:
    run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.owner_user_id == current_user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    return run



@router.get("/research/runs/{run_id}/plan")
def get_research_run_plan(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the bounded, actionable plan associated with an owned research run."""
    run = db.scalar(
        select(ResearchRun).where(
            ResearchRun.id == run_id,
            ResearchRun.owner_user_id == current_user.id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    configuration = run.configuration or {}
    plan = configuration.get("research_plan")
    if not plan:
        # Backward-compatible response for runs created before plans were persisted.
        plan = build_research_plan(run.question, run.mode, run.max_sources)
    return {
        "run_id": run.id,
        "mode": run.mode,
        "run_status": run.status,
        "plan": plan,
    }
