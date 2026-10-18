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
from app.core.security import get_current_user
from app.models.entities import Paper, PaperDependency, PaperVersion, Passage, SourceEvent, User
from app.schemas.evidence import PaperImport, PaperRead, PaperSearchResult, SourceEventCreate, SourceEventRead
from app.services.academic_search import search_papers
from app.services.audit import record_audit_event
from app.services.temporal_impact import affected_report_runs, impacted_claims, impacted_papers, mark_review_required

router = APIRouter(tags=["sources"], dependencies=[Depends(get_current_user)])
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
def import_paper(payload: PaperImport, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Paper:
    doi = normalize_doi(payload.doi)
    existing = None
    if doi:
        existing = db.scalar(select(Paper).where(func.lower(Paper.doi) == doi.lower(), Paper.owner_user_id == current_user.id))
    if existing is None and payload.external_id:
        existing = db.scalar(select(Paper).where(
            Paper.source_provider == payload.provider,
            Paper.external_id == payload.external_id,
            Paper.owner_user_id == current_user.id,
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
        owner_user_id=current_user.id,
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
    current_user: User = Depends(get_current_user),
) -> dict:
    rows = db.execute(
        select(SourceEvent, Paper.title)
        .join(Paper, Paper.id == SourceEvent.paper_id)
        .where(Paper.owner_user_id == current_user.id)
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
    current_user: User = Depends(get_current_user),
) -> list[Paper]:
    statement = select(Paper).where(Paper.owner_user_id == current_user.id).order_by(Paper.created_at.desc()).limit(limit)
    if q:
        statement = select(Paper).where(Paper.owner_user_id == current_user.id, Paper.title.ilike(f"%{q.strip()}%")).order_by(Paper.created_at.desc()).limit(limit)
    return list(db.scalars(statement).all())


@router.get("/sources/papers/{paper_id}", response_model=PaperRead)
def get_paper(paper_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Paper:
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id))
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return paper


@router.get("/sources/papers/{paper_id}/status-check")
async def check_paper_status(paper_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    """Preview post-publication signals without auto-changing saved evidence status."""
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id))
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    if not paper.doi:
        return {
            "paper_id": paper.id,
            "doi": None,
            "signals": [],
            "providers": {"crossref": "skipped_no_doi", "openalex": "skipped_no_doi"},
            "note": "This paper has no DOI. No automatic status signal could be checked; use the source notice form for manual review.",
        }

    from urllib.parse import quote

    doi = normalize_doi(paper.doi)
    headers = {"User-Agent": "Chronicle/0.1.0 (https://github.com/affanSkhan/chronicle)", "Accept": "application/json"}
    timeout = httpx.Timeout(20.0, connect=8.0)
    providers: dict[str, str] = {}
    signals: list[dict] = []

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        # Crossref update-to records indicate items that update this DOI, including
        # correction/retraction notices where those relationships were deposited.
        try:
            response = await client.get(f"https://api.crossref.org/works/{quote(doi or '', safe='/')}")
            response.raise_for_status()
            item = response.json().get("message", {})
            providers["crossref"] = "ok"
            for update in item.get("update-to") or []:
                update_type_raw = str(update.get("type") or "metadata_change").strip().lower()
                mapped = {
                    "retraction": "retraction",
                    "correction": "correction",
                    "expression-of-concern": "expression_of_concern",
                    "expression_of_concern": "expression_of_concern",
                    "removal": "retraction",
                }.get(update_type_raw, "metadata_change")
                update_doi = normalize_doi(update.get("DOI"))
                signals.append({
                    "provider": "crossref",
                    "event_type": mapped,
                    "update_type": update_type_raw,
                    "description": str(update.get("label") or f"Crossref reports an update relationship of type '{update_type_raw}'."),
                    "source_url": f"https://doi.org/{update_doi}" if update_doi else None,
                    "verification_status": "metadata_confirmed",
                    "metadata": update,
                })
        except Exception:
            providers["crossref"] = "unavailable"

        # OpenAlex exposes is_retracted based on Retraction Watch coverage.
        try:
            response = await client.get(
                "https://api.openalex.org/works",
                params={
                    "filter": f"doi:https://doi.org/{doi}",
                    "per-page": 1,
                    "select": "id,doi,title,is_retracted,updated_date",
                },
            )
            response.raise_for_status()
            results = response.json().get("results") or []
            matched = results[0] if results else None
            providers["openalex"] = "ok" if matched else "not_found"
            if matched and matched.get("is_retracted") is True and not any(signal["event_type"] == "retraction" for signal in signals):
                signals.append({
                    "provider": "openalex",
                    "event_type": "retraction",
                    "update_type": "is_retracted",
                    "description": "OpenAlex marks this work as retracted. Confirm the underlying notice before recording a verified event.",
                    "source_url": matched.get("id"),
                    "verification_status": "metadata_confirmed",
                    "metadata": {"openalex_id": matched.get("id"), "updated_date": matched.get("updated_date")},
                })
        except Exception:
            providers["openalex"] = "unavailable"

    return {
        "paper_id": paper.id,
        "doi": doi,
        "providers": providers,
        "signals": signals,
        "note": "This is a metadata status-check preview, not exhaustive surveillance. No event or publication status was changed. Verify the source notice and record an event to trigger downstream impact analysis.",
    }


@router.post("/sources/papers/{paper_id}/events", response_model=dict, status_code=201)
def record_source_event(
    paper_id: str,
    payload: SourceEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id))
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")

    normalized_description = payload.description.strip()
    duplicate = db.scalar(select(SourceEvent).where(
        SourceEvent.paper_id == paper_id,
        SourceEvent.event_type == payload.event_type,
        SourceEvent.event_date == payload.event_date,
        SourceEvent.source_url == payload.source_url,
        SourceEvent.description == normalized_description,
        SourceEvent.verification_status == payload.verification_status,
    ).order_by(SourceEvent.observed_at.desc()))
    if duplicate is not None:
        snapshot = duplicate.metadata_snapshot if isinstance(duplicate.metadata_snapshot, dict) else {}
        impact_summary = snapshot.get("impact_summary", {}) if isinstance(snapshot.get("impact_summary"), dict) else {}
        impacted_paper_ids = snapshot.get("impacted_paper_ids", [paper_id])
        affected_claim_ids = snapshot.get("affected_claim_ids", [])
        affected_run_ids = snapshot.get("affected_run_ids", [])
        return {
            "event": SourceEventRead.model_validate(duplicate).model_dump(mode="json"),
            "source_status_updated": duplicate.verification_status != "unverified",
            "duplicate": True,
            "impact": {
                "impacted_paper_ids": impacted_paper_ids,
                "paper_reasons": {},
                "affected_claim_ids": affected_claim_ids,
                "claim_reasons": {},
                "claims_flagged_for_review": impact_summary.get("claims_flagged_for_review", 0),
                "affected_run_ids": affected_run_ids,
                "report_versions_flagged_for_review": impact_summary.get("report_versions_flagged_for_review", 0),
            },
            "note": "The same source event and verification status were already recorded; the existing event was returned without duplicating versions or audit records.",
        }

    event = SourceEvent(
        paper_id=paper_id,
        event_type=payload.event_type,
        event_date=payload.event_date,
        source_url=payload.source_url,
        description=normalized_description,
        verification_status=payload.verification_status,
        metadata_snapshot=payload.metadata_snapshot,
    )
    db.add(event)
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=None,
        target_entity_type="source_event",
        target_entity_id=event.id,
        action="source_event.recorded",
        previous_value=None,
        new_value={
            "paper_id": paper_id,
            "event_type": event.event_type,
            "verification_status": event.verification_status,
            "source_url": event.source_url,
            "description": event.description,
        },
        reason="Source lifecycle event recorded by a researcher.",
        resolution_status=event.verification_status,
    )

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
    from app.models.entities import Claim, ReportVersion
    claims_before = {
        claim.id: {
            "assessment": claim.assessment,
            "review_required": claim.review_required,
            "run_id": claim.run_id,
        }
        for claim in db.scalars(select(Claim).where(Claim.id.in_(claim_ids))).all()
    } if claim_ids else {}
    reviewed_count = mark_review_required(db, claim_ids)
    run_ids = affected_report_runs(db, claim_ids)
    # A report may cite/discover a source without producing a claim for it yet.
    # Include runs whose saved report snapshot contains any impacted paper or passage.
    all_reports = list(db.scalars(select(ReportVersion)).all())
    impacted_passage_ids = set(db.scalars(
        select(Passage.id).join(PaperVersion, Passage.paper_version_id == PaperVersion.id)
        .where(PaperVersion.paper_id.in_(paper_ids))
    ).all()) if paper_ids else set()
    for report in all_reports:
        snapshot = report.evidence_snapshot if isinstance(report.evidence_snapshot, dict) else {}
        snapshot_papers = set(snapshot.get("paper_ids", [])) if isinstance(snapshot.get("paper_ids"), list) else set()
        snapshot_passages = set(snapshot.get("passage_ids", [])) if isinstance(snapshot.get("passage_ids"), list) else set()
        if (snapshot_papers & paper_ids) or (snapshot_passages & impacted_passage_ids):
            run_ids.add(report.run_id)

    report_versions = [report for report in all_reports if report.run_id in run_ids]
    reports_before = {report.id: {"review_required": report.review_required, "run_id": report.run_id} for report in report_versions}
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
    for claim_id in sorted(claim_ids):
        before = claims_before.get(claim_id, {})
        claim = db.get(Claim, claim_id)
        if claim is None:
            continue
        record_audit_event(
            db,
            actor_user_id=current_user.id,
            run_id=claim.run_id,
            target_entity_type="claim",
            target_entity_id=claim.id,
            action="claim.flagged_by_source_event",
            previous_value={"assessment": before.get("assessment"), "review_required": before.get("review_required")},
            new_value={"assessment": claim.assessment, "review_required": claim.review_required},
            reason=f"Source event {event.id} may affect evidence linked to this claim.",
            resolution_status="needs_review",
        )
    for report in report_versions:
        before = reports_before.get(report.id, {})
        record_audit_event(
            db,
            actor_user_id=current_user.id,
            run_id=report.run_id,
            target_entity_type="report_version",
            target_entity_id=report.id,
            action="report_version.flagged_by_source_event",
            previous_value={"review_required": before.get("review_required")},
            new_value={"review_required": report.review_required, "version_number": report.version_number},
            reason=f"Source event {event.id} may affect this saved report snapshot.",
            resolution_status="needs_review",
        )
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
def list_source_events(paper_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[SourceEvent]:
    if db.scalar(select(Paper.id).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id)) is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return list(db.scalars(select(SourceEvent).where(SourceEvent.paper_id == paper_id).order_by(SourceEvent.observed_at.desc())).all())
