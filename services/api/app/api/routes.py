from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entities import ResearchProject, ResearchRun
from app.schemas.research import ProjectCreate, ProjectRead, ResearchRun as ResearchRunSchema, ResearchRunCreate
from app.services.research_pipeline import execute_research_run

router = APIRouter(tags=["research"])


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ResearchProject:
    project = ResearchProject(title=payload.title.strip(), research_question=payload.research_question.strip())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)) -> list[ResearchProject]:
    return list(db.scalars(select(ResearchProject).order_by(ResearchProject.updated_at.desc())).all())


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db)) -> ResearchProject:
    project = db.get(ResearchProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found.")
    return project


@router.post("/research/runs", response_model=ResearchRunSchema, status_code=201)
def create_research_run(payload: ResearchRunCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> ResearchRun:
    if payload.project_id and db.get(ResearchProject, payload.project_id) is None:
        raise HTTPException(status_code=404, detail="Research project not found.")
    run = ResearchRun(
        project_id=payload.project_id,
        question=payload.question.strip(),
        mode=payload.mode.value,
        status="queued",
        max_sources=payload.max_sources,
        demo=not payload.execute,
        configuration={"pipeline": "scholarly-metadata-discovery" if payload.execute else "request-only-demo", "max_sources": payload.max_sources},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    if payload.execute:
        background_tasks.add_task(execute_research_run, run.id)
    return run


@router.get("/research/runs", response_model=list[ResearchRunSchema])
def list_research_runs(db: Session = Depends(get_db)) -> list[ResearchRun]:
    return list(db.scalars(select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(100)).all())


@router.get("/research/runs/{run_id}", response_model=ResearchRunSchema)
def get_research_run(run_id: str, db: Session = Depends(get_db)) -> ResearchRun:
    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    return run
