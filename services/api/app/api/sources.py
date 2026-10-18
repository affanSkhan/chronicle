from datetime import datetime, timezone
from pathlib import Path
import hashlib
import re

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.entities import Paper, PaperDependency, PaperVersion, SourceEvent
from app.schemas.evidence import PaperImport, PaperRead, PaperSearchResult, SourceEventCreate, SourceEventRead
from app.services.academic_search import search_papers
from app.services.temporal_impact import affected_report_runs, impacted_claims, impacted_papers, mark_review_required

router = APIRouter(tags=["sources"])
settings = get_settings()


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.strip().rstrip(".") or None


@router.get("/sources/search")
async def search_academic_sources(
    q: str = Query(min_length=3, max_length=500),
    provider: str = Query(default="all", pattern="^(all|crossref|openalex)$"),
    limit: int = Query(default=10, ge=1, le=25),
) -> dict:
    try:
        return await search_papers(q.strip(), limit=limit, provider=provider)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Scholarly metadata providers are currently unavailable.") from exc


@router.post("/sources/papers", response_model=PaperRead, status_code=201)
def import_paper(payload: PaperImport, db: Session = Depends(get_db)) -> Paper:
    doi = normalize_doi(payload.doi)
    existing = None
    if doi:
        existing = db.scalar(select(Paper).where(func.lower(Paper.doi) == doi.lower()))
    if existing is None and payload.external_id:
        existing = db.scalar(select(Paper).where(
            Paper.source_provider == payload.provider,
            Paper.external_id == payload.external_id,
        ))
    if existing:
        if not existing.abstract and payload.abstract:
            existing.abstract = payload.abstract
        if not existing.authors and payload.authors:
            existing.authors = payload.authors
        if not existing.landing_url and payload.landing_url:
            existing.landing_url = payload.landing_url
        db.commit()
        db.refresh(existing)
        return existing

    paper = Paper(
        doi=doi,
        title=payload.title.strip(),
        authors=payload.authors,
        abstract=payload.abstract,
        publication_year=payload.publication_year,
        publisher=payload.publisher,
        source_provider=payload.provider,
        external_id=payload.external_id,
        landing_url=payload.landing_url,
    )
    db.add(paper)
    db.flush()
    db.add(PaperVersion(
        paper_id=paper.id,
        version_label="metadata-import",
        publication_status="unknown",
        metadata_snapshot={"provider": payload.provider, "imported_at": datetime.now(timezone.utc).isoformat()},
    ))
    db.commit()
    db.refresh(paper)
    return paper


@router.get("/sources/events")
def list_recent_source_events(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        select(SourceEvent, Paper.title)
        .join(Paper, Paper.id == SourceEvent.paper_id)
        .order_by(SourceEvent.observed_at.desc())
        .limit(limit)
    ).all()
    return {
        "events": [{
            "id": event.id,
            "paper_id": event.paper_id,
            "paper_title": paper_title,
            "event_type": event.event_type,
            "event_date": event.event_date.isoformat() if event.event_date else None,
            "observed_at": event.observed_at.isoformat(),
            "source_url": event.source_url,
            "description": event.description,
            "verification_status": event.verification_status,
            "metadata_snapshot": event.metadata_snapshot,
        } for event, paper_title in rows],
        "count": len(rows),
        "note": "Events are recorded from manual submissions in the current version. Scheduled publisher/retraction-feed monitoring is not enabled.",
    }


@router.get("/sources/papers", response_model=list[PaperRead])
def list_papers(
    q: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[Paper]:
    statement = select(Paper).order_by(Paper.created_at.desc()).limit(limit)
    if q:
        statement = select(Paper).where(Paper.title.ilike(f"%{q.strip()}%")).order_by(Paper.created_at.desc()).limit(limit)
    return list(db.scalars(statement).all())


@router.get("/sources/papers/{paper_id}", response_model=PaperRead)
def get_paper(paper_id: str, db: Session = Depends(get_db)) -> Paper:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return paper


@router.post("/sources/papers/{paper_id}/events", response_model=dict, status_code=201)
def record_source_event(
    paper_id: str,
    payload: SourceEventCreate,
    db: Session = Depends(get_db),
) -> dict:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")

    event = SourceEvent(
        paper_id=paper_id,
        event_type=payload.event_type,
        event_date=payload.event_date,
        source_url=payload.source_url,
        description=payload.description.strip(),
        verification_status=payload.verification_status,
        metadata_snapshot=payload.metadata_snapshot,
    )
    db.add(event)
    db.flush()

    latest = db.scalar(select(PaperVersion).where(PaperVersion.paper_id == paper_id).order_by(PaperVersion.retrieved_at.desc()))
    status_map = {
        "correction": "corrected",
        "retraction": "retracted",
        "expression_of_concern": "expression_of_concern",
        "new_version": "published",
    }
    effective_status = status_map.get(payload.event_type, latest.publication_status if latest else "unknown")
    if payload.verification_status == "unverified":
        effective_status = latest.publication_status if latest else "unknown"
    db.add(PaperVersion(
        paper_id=paper_id,
        version_label=f"event-{event.id[:8]}",
        publication_status=effective_status,
        publication_date=payload.event_date,
        status_url=payload.source_url,
        metadata_snapshot={
            "source_event_id": event.id,
            "event_type": payload.event_type,
            "verification_status": payload.verification_status,
            "description": payload.description,
            "supersedes_version_id": latest.id if latest else None,
        },
    ))

    paper_ids, paper_reasons = impacted_papers(db, paper_id)
    claim_ids, claim_reasons = impacted_claims(db, paper_ids)
    reviewed_count = mark_review_required(db, claim_ids)
    run_ids = affected_report_runs(db, claim_ids)

    from app.models.entities import ReportVersion
    report_versions = list(db.scalars(select(ReportVersion).where(ReportVersion.run_id.in_(run_ids))).all()) if run_ids else []
    for report in report_versions:
        report.review_required = True
        if not report.change_summary:
            report.change_summary = "A source event affected evidence used by this report; review is required."
    event.metadata_snapshot = {
        **(event.metadata_snapshot or {}),
        "impact_summary": {
            "impacted_paper_count": len(paper_ids),
            "affected_claim_count": len(claim_ids),
            "claims_flagged_for_review": reviewed_count,
            "affected_run_count": len(run_ids),
            "report_versions_flagged_for_review": len(report_versions),
        },
        "impacted_paper_ids": sorted(paper_ids),
        "affected_claim_ids": sorted(claim_ids),
        "affected_run_ids": sorted(run_ids),
    }
    db.commit()
    db.refresh(event)

    return {
        "event": SourceEventRead.model_validate(event).model_dump(mode="json"),
        "source_status_updated": payload.verification_status != "unverified",
        "impact": {
            "impacted_paper_ids": sorted(paper_ids),
            "paper_reasons": paper_reasons,
            "affected_claim_ids": sorted(claim_ids),
            "claim_reasons": claim_reasons,
            "claims_flagged_for_review": reviewed_count,
            "affected_run_ids": sorted(run_ids),
            "report_versions_flagged_for_review": len(report_versions),
        },
        "note": "Source events trigger review; they do not automatically prove dependent claims false. Event verification should be checked against the cited provider.",
    }


@router.get("/sources/papers/{paper_id}/events", response_model=list[SourceEventRead])
def list_source_events(paper_id: str, db: Session = Depends(get_db)) -> list[SourceEvent]:
    if db.get(Paper, paper_id) is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return list(db.scalars(select(SourceEvent).where(SourceEvent.paper_id == paper_id).order_by(SourceEvent.observed_at.desc())).all())
