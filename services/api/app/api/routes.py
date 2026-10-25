from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import ResearchProject, ResearchRun, User
from app.schemas.research import ProjectCreate, ProjectRead, ProjectUpdate, ResearchRun as ResearchRunSchema, ResearchRunCreate
from app.services.audit import record_audit_event
from app.services.research_pipeline import execute_research_run

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
def list_projects(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ResearchProject]:
    statement = select(ResearchProject).where(ResearchProject.owner_user_id == current_user.id)
    if not include_archived:
        statement = statement.where(ResearchProject.archived_at.is_(None))
    return list(db.scalars(statement.order_by(ResearchProject.updated_at.desc())).all())


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ResearchProject:
    project = db.scalar(select(ResearchProject).where(ResearchProject.id == project_id, ResearchProject.owner_user_id == current_user.id))
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found.")
    return project


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ResearchProject:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Provide at least one project field to update.")
    project = db.scalar(select(ResearchProject).where(ResearchProject.id == project_id, ResearchProject.owner_user_id == current_user.id))
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found.")
    previous = {"title": project.title, "research_question": project.research_question, "archived_at": project.archived_at.isoformat() if project.archived_at else None}
    if "title" in updates and updates["title"] is not None:
        project.title = updates["title"].strip()
    if "research_question" in updates and updates["research_question"] is not None:
        project.research_question = updates["research_question"].strip()
    if "archived" in updates and updates["archived"] is not None:
        if updates["archived"] and project.archived_at is None:
            project.archived_at = datetime.now(timezone.utc)
        elif not updates["archived"]:
            project.archived_at = None
    db.flush()
    record_audit_event(db, actor_user_id=current_user.id, run_id=None, target_entity_type="research_project", target_entity_id=project.id, action="research_project.updated", previous_value=previous, new_value={"title": project.title, "research_question": project.research_question, "archived_at": project.archived_at.isoformat() if project.archived_at else None}, reason="Research workspace updated.")
    db.commit()
    db.refresh(project)
    return project


@router.post("/research/runs", response_model=ResearchRunSchema, status_code=201)
def create_research_run(payload: ResearchRunCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ResearchRun:
    if payload.project_id:
        project = db.scalar(select(ResearchProject).where(ResearchProject.id == payload.project_id, ResearchProject.owner_user_id == current_user.id))
        if project is None:
            raise HTTPException(status_code=404, detail="Research project not found.")
        if project.archived_at is not None:
            raise HTTPException(status_code=409, detail="This workspace is archived. Restore it before starting a new research run.")
    run = ResearchRun(
        owner_user_id=current_user.id,
        project_id=payload.project_id,
        question=payload.question.strip(),
        mode=payload.mode.value,
        status="queued",
        max_sources=payload.max_sources,
        demo=not payload.execute,
        configuration={"pipeline": "scholarly-metadata-discovery" if payload.execute else "request-only-demo", "max_sources": payload.max_sources},
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


@router.post("/research/runs/{run_id}/cancel", response_model=ResearchRunSchema)
def cancel_research_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ResearchRun:
    run = db.scalar(select(ResearchRun).where(
        ResearchRun.id == run_id,
        ResearchRun.owner_user_id == current_user.id,
    ))
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")

    previous_status = run.status
    if run.status == "queued":
        run.status = "cancelled"
        run.cancelled_at = datetime.now(timezone.utc)
    elif run.status == "running":
        run.status = "cancel_requested"
        run.cancel_requested_at = datetime.now(timezone.utc)
    elif run.status == "cancel_requested":
        return run
    elif run.status == "cancelled":
        return run
    else:
        raise HTTPException(status_code=409, detail=f"Run cannot be cancelled from status '{run.status}'.")

    run.configuration = {
        **(run.configuration or {}),
        "cancellation": {
            "requested_at": (run.cancel_requested_at or run.cancelled_at).isoformat(),
            "requested_by": current_user.id,
            "previous_status": previous_status,
        },
    }
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=run.id,
        target_entity_type="research_run",
        target_entity_id=run.id,
        action="research_run.cancel_requested" if run.status == "cancel_requested" else "research_run.cancelled",
        previous_value={"status": previous_status},
        new_value={"status": run.status, "cancel_requested_at": run.cancel_requested_at.isoformat() if run.cancel_requested_at else None, "cancelled_at": run.cancelled_at.isoformat() if run.cancelled_at else None},
        reason="Cancellation requested by the workspace owner.",
        resolution_status="needs_review" if run.status == "cancel_requested" else "cancelled",
    )
    db.commit()
    db.refresh(run)
    return run


@router.post("/research/runs/{run_id}/retry", response_model=ResearchRunSchema, status_code=201)
def retry_research_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ResearchRun:
    original = db.scalar(select(ResearchRun).where(
        ResearchRun.id == run_id,
        ResearchRun.owner_user_id == current_user.id,
    ))
    if original is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    if original.status not in {"failed", "cancelled", "completed_with_limitations"}:
        raise HTTPException(
            status_code=409,
            detail="Only failed, cancelled, or completed-with-limitations runs can be retried.",
        )
    if original.project_id:
        project = db.scalar(select(ResearchProject).where(
            ResearchProject.id == original.project_id,
            ResearchProject.owner_user_id == current_user.id,
        ))
        if project is None:
            raise HTTPException(status_code=404, detail="Research project not found.")
        if project.archived_at is not None:
            raise HTTPException(status_code=409, detail="This workspace is archived. Restore it before retrying the run.")

    retry = ResearchRun(
        owner_user_id=current_user.id,
        project_id=original.project_id,
        question=original.question,
        mode=original.mode,
        status="queued",
        max_sources=original.max_sources,
        demo=False,
        retry_of_run_id=original.id,
        configuration={
            "pipeline": "mode-specific-scholarly-discovery",
            "retry_of_run_id": original.id,
            "retried_at": datetime.now(timezone.utc).isoformat(),
            "retry_policy": "fresh_run_with_original_question_mode_source_budget",
        },
    )
    db.add(retry)
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=retry.id,
        target_entity_type="research_run",
        target_entity_id=retry.id,
        action="research_run.retried",
        previous_value={"original_run_id": original.id, "original_status": original.status},
        new_value={"retry_run_id": retry.id, "status": retry.status, "mode": retry.mode, "max_sources": retry.max_sources},
        reason="Owner requested a fresh retry using the original run parameters.",
    )
    db.commit()
    db.refresh(retry)
    background_tasks.add_task(execute_research_run, retry.id)
    return retry


@router.get("/research/runs/{run_id}", response_model=ResearchRunSchema)
def get_research_run(run_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ResearchRun:
    run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.owner_user_id == current_user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    return run
