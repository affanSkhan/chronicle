from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import re

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_llm_config, get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import Claim, EvidenceRelation, Paper, PaperDependency, PaperVersion, Passage, ResearchRun, SourceEvent, SourceStatusCheck, User
from app.schemas.evidence import PaperImport, PaperMonitoringUpdate, PaperRead, PaperSearchResult, SourceEventCreate, SourceEventRead
from app.services.academic_search import search_papers
from app.services.citation_verification import verify_claim_with_llm
from app.services.source_status import fetch_paper_status_signals, stable_signal_fingerprint
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
        "note": "Source events are manually recorded. Scheduled Crossref/OpenAlex metadata checks are stored separately as status-check history and do not automatically create source events.",
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
async def check_paper_status(
    paper_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Preview post-publication signals without writing a check or changing source status."""
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id))
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    result = await fetch_paper_status_signals(paper.doi or "")
    return {
        "paper_id": paper.id,
        "doi": normalize_doi(paper.doi),
        **result,
        "note": result.get("note", "") + " This GET endpoint is a preview only; use POST to save a monitored check.",
    }


@router.post("/sources/papers/{paper_id}/status-check", status_code=201)
async def record_paper_status_check(
    paper_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Manually check and persist status signals without applying them to the paper."""
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id))
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")

    checked_at = datetime.now(timezone.utc)
    result = await fetch_paper_status_signals(paper.doi or "")
    provider_states = result.get("providers", {})
    signals = result.get("signals", [])
    stable_signals = stable_signal_fingerprint(signals)
    result_hash = hashlib.sha256(
        json.dumps(stable_signals, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    latest = db.scalar(
        select(SourceStatusCheck)
        .where(SourceStatusCheck.paper_id == paper.id)
        .order_by(SourceStatusCheck.checked_at.desc())
    )
    previous_hash = latest.result_hash if latest else None
    states = list(provider_states.values())
    if not paper.doi:
        outcome = "no_doi"
    elif states and all(state in {"unavailable", "skipped_no_doi"} for state in states):
        outcome = "unavailable"
    elif any(state == "unavailable" for state in states):
        outcome = "partial"
    else:
        outcome = "ok"
    complete_provider_result = any(state in {"ok", "not_found"} for state in states)
    change_detected = bool(
        previous_hash is not None
        and complete_provider_result
        and outcome in {"ok", "partial"}
        and previous_hash != result_hash
    )

    check = SourceStatusCheck(
        paper_id=paper.id,
        checked_at=checked_at,
        trigger_type="manual",
        outcome=outcome,
        provider_states=provider_states,
        signals=signals,
        result_hash=result_hash,
        previous_result_hash=previous_hash,
        change_detected=change_detected,
        error_message="One or more metadata providers were unavailable." if outcome in {"partial", "unavailable"} else None,
    )
    db.add(check)
    paper.last_status_check_at = checked_at
    paper.next_status_check_at = (
        checked_at + timedelta(minutes=paper.monitor_interval_minutes)
        if paper.monitoring_enabled else None
    )
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=None,
        target_entity_type="source_status_check",
        target_entity_id=check.id,
        action="source_status_check.manual_completed",
        previous_value={"result_hash": previous_hash},
        new_value={
            "result_hash": result_hash,
            "change_detected": change_detected,
            "outcome": outcome,
            "signal_count": len(signals),
            "monitoring_enabled": paper.monitoring_enabled,
        },
        reason="Manual external source-status check saved. Signals remain pending human review.",
        resolution_status="needs_review" if change_detected or signals else "recorded",
    )
    db.commit()
    db.refresh(check)
    return {
        "id": check.id,
        "paper_id": paper.id,
        "paper_title": paper.title,
        "doi": normalize_doi(paper.doi),
        "checked_at": check.checked_at.isoformat(),
        "trigger_type": check.trigger_type,
        "outcome": check.outcome,
        "provider_states": check.provider_states,
        "signals": check.signals,
        "change_detected": check.change_detected,
        "previous_result_hash": check.previous_result_hash,
        "result_hash": check.result_hash,
        "monitoring_enabled": paper.monitoring_enabled,
        "next_status_check_at": paper.next_status_check_at.isoformat() if paper.next_status_check_at else None,
        "note": result.get("note", "") + " No event was created and no publication status was changed.",
    }


@router.patch("/sources/papers/{paper_id}/monitoring")
def update_paper_monitoring(
    paper_id: str,
    payload: PaperMonitoringUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id))
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    before = {
        "monitoring_enabled": paper.monitoring_enabled,
        "monitor_interval_minutes": paper.monitor_interval_minutes,
        "next_status_check_at": paper.next_status_check_at.isoformat() if paper.next_status_check_at else None,
    }
    now = datetime.now(timezone.utc)
    paper.monitoring_enabled = payload.enabled
    paper.monitor_interval_minutes = payload.interval_minutes
    paper.next_status_check_at = now if payload.enabled else None
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=None,
        target_entity_type="paper",
        target_entity_id=paper.id,
        action="paper.monitoring_updated",
        previous_value=before,
        new_value={
            "monitoring_enabled": paper.monitoring_enabled,
            "monitor_interval_minutes": paper.monitor_interval_minutes,
            "next_status_check_at": paper.next_status_check_at.isoformat() if paper.next_status_check_at else None,
        },
        reason="Source status monitoring configuration updated by the paper owner.",
    )
    db.commit()
    db.refresh(paper)
    return {
        "paper_id": paper.id,
        "monitoring_enabled": paper.monitoring_enabled,
        "monitor_interval_minutes": paper.monitor_interval_minutes,
        "last_status_check_at": paper.last_status_check_at.isoformat() if paper.last_status_check_at else None,
        "next_status_check_at": paper.next_status_check_at.isoformat() if paper.next_status_check_at else None,
        "note": "Scheduled checks only record source-status changes for researcher review; they do not automatically create events or change publication status.",
    }


def _status_check_payload(check: SourceStatusCheck, paper_title: str, doi: str | None) -> dict:
    return {
        "id": check.id,
        "paper_id": check.paper_id,
        "paper_title": paper_title,
        "doi": normalize_doi(doi),
        "checked_at": check.checked_at.isoformat(),
        "trigger_type": check.trigger_type,
        "outcome": check.outcome,
        "provider_states": check.provider_states,
        "signals": check.signals,
        "change_detected": check.change_detected,
        "previous_result_hash": check.previous_result_hash,
        "result_hash": check.result_hash,
        "error_message": check.error_message,
    }


@router.get("/sources/status-checks")
def list_status_checks(
    limit: int = Query(default=50, ge=1, le=200),
    changes_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    statement = (
        select(SourceStatusCheck, Paper.title, Paper.doi)
        .join(Paper, Paper.id == SourceStatusCheck.paper_id)
        .where(Paper.owner_user_id == current_user.id)
        .order_by(SourceStatusCheck.checked_at.desc())
    )
    if changes_only:
        statement = statement.where(SourceStatusCheck.change_detected.is_(True))
    rows = db.execute(statement.limit(limit)).all()
    return {
        "count": len(rows),
        "checks": [_status_check_payload(check, title, doi) for check, title, doi in rows],
        "note": "Provider signals are review prompts, not authoritative automatic publication-status changes.",
    }


@router.get("/sources/papers/{paper_id}/status-checks")
def list_paper_status_checks(
    paper_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id))
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    rows = db.scalars(
        select(SourceStatusCheck)
        .where(SourceStatusCheck.paper_id == paper.id)
        .order_by(SourceStatusCheck.checked_at.desc())
        .limit(limit)
    ).all()
    return {
        "paper_id": paper.id,
        "count": len(rows),
        "checks": [_status_check_payload(check, paper.title, paper.doi) for check in rows],
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

    # Include runs whose saved report snapshot contains an impacted source,
    # even when claim extraction did not produce a claim for that paper.
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

    # A prior report is an immutable historical snapshot. Create one child
    # version per affected run and flag the new version for human reassessment.
    latest_by_run: dict[str, ReportVersion] = {}
    for report in all_reports:
        if report.run_id not in run_ids:
            continue
        prior = latest_by_run.get(report.run_id)
        if prior is None or report.version_number > prior.version_number:
            latest_by_run[report.run_id] = report

    event_metadata = event.metadata_snapshot if isinstance(event.metadata_snapshot, dict) else {}
    event_metadata = {
        **event_metadata,
        "impact_summary": {
            "impacted_paper_count": len(paper_ids),
            "affected_claim_count": len(claim_ids),
            "claims_flagged_for_review": reviewed_count,
            "affected_run_count": len(run_ids),
            "report_versions_flagged_for_review": len(latest_by_run),
        },
        "impacted_paper_ids": sorted(paper_ids),
        "affected_claim_ids": sorted(claim_ids),
        "affected_run_ids": sorted(run_ids),
    }
    event.metadata_snapshot = event_metadata

    new_report_versions: list[tuple[ReportVersion, ReportVersion]] = []
    for prior in latest_by_run.values():
        prior_snapshot = prior.evidence_snapshot if isinstance(prior.evidence_snapshot, dict) else {}
        next_snapshot = {
            **prior_snapshot,
            "previous_report_version_id": prior.id,
            "source_update_requires_review": True,
            "last_source_event": {
                "id": event.id,
                "paper_id": paper_id,
                "event_type": event.event_type,
                "event_date": event.event_date.isoformat() if event.event_date else None,
                "observed_at": event.observed_at.isoformat(),
                "source_url": event.source_url,
                "description": event.description,
                "verification_status": event.verification_status,
            },
            "impact_summary": event_metadata["impact_summary"],
        }
        update_notice = (
            f"\n\n---\n\n## Temporal source update\n\n"
            f"Chronicle recorded a **{event.event_type.replace('_', ' ')}** event for a source in this report "
            f"(verification status: **{event.verification_status}**).\n\n"
            f"**Notice:** {event.description}\n\n"
            "This version preserves the prior analysis and flags it for researcher review. "
            "It does not assume that every dependent claim is false.\n"
        )
        revised = ReportVersion(
            run_id=prior.run_id,
            version_number=prior.version_number + 1,
            parent_version_id=prior.id,
            title=prior.title,
            content_markdown=prior.content_markdown + update_notice,
            evidence_snapshot=next_snapshot,
            change_summary=f"Source event {event.id} ({event.event_type}) recorded; prior conclusions require reassessment.",
            review_required=True,
        )
        db.add(revised)
        db.flush()
        new_report_versions.append((prior, revised))

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
    for prior, revised in new_report_versions:
        record_audit_event(
            db,
            actor_user_id=current_user.id,
            run_id=revised.run_id,
            target_entity_type="report_version",
            target_entity_id=revised.id,
            action="report_version.created_after_source_event",
            previous_value={
                "parent_report_version_id": prior.id,
                "version_number": prior.version_number,
                "review_required": prior.review_required,
            },
            new_value={
                "parent_report_version_id": revised.parent_version_id,
                "version_number": revised.version_number,
                "review_required": revised.review_required,
            },
            reason=f"Source event {event.id} requires reassessment of the saved evidence snapshot.",
            resolution_status="needs_review",
        )
    report_versions = [revised for _, revised in new_report_versions]
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


@router.post("/sources/events/{event_id}/reverify-impacted-claims")
async def reverify_impacted_claims_for_source_event(
    event_id: str,
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Manually re-check claims affected by a recorded source event.

    This action is explicitly triggered by a researcher. It does not convert an
    unverified source signal into proof, automatically invalidate any claim, or
    clear the human-review flag.
    """
    event_row = db.execute(
        select(SourceEvent, Paper.title)
        .join(Paper, Paper.id == SourceEvent.paper_id)
        .where(SourceEvent.id == event_id, Paper.owner_user_id == current_user.id)
    ).first()
    if event_row is None:
        raise HTTPException(status_code=404, detail="Source event not found.")
    source_event, source_title = event_row
    metadata = source_event.metadata_snapshot if isinstance(source_event.metadata_snapshot, dict) else {}
    raw_claim_ids = metadata.get("affected_claim_ids", [])
    affected_ids = list(dict.fromkeys(
        value for value in raw_claim_ids if isinstance(value, str)
    )) if isinstance(raw_claim_ids, list) else []

    claims = list(db.scalars(
        select(Claim)
        .join(ResearchRun, Claim.run_id == ResearchRun.id)
        .where(Claim.id.in_(affected_ids), ResearchRun.owner_user_id == current_user.id)
        .order_by(Claim.created_at.asc())
        .limit(limit)
    ).all()) if affected_ids else []

    if not claims:
        return {
            "event_id": source_event.id,
            "event_type": source_event.event_type,
            "source_verification_status": source_event.verification_status,
            "rechecked_count": 0,
            "skipped_count": 0,
            "results": [],
            "note": "This event has no saved affected claims accessible in your account. No claim was changed.",
        }

    api_key, api_base, model = get_llm_config(get_settings())
    if not api_key or not model:
        raise HTTPException(
            status_code=503,
            detail="Targeted source-event re-verification requires LLM_API_KEY and LLM_MODEL (or legacy OPENAI_API_KEY and OPENAI_MODEL). No claim was changed.",
        )

    results: list[dict] = []
    rechecked_count = 0
    skipped_count = 0
    for claim in claims:
        relations = db.scalars(
            select(EvidenceRelation).where(
                EvidenceRelation.claim_id == claim.id,
                EvidenceRelation.passage_id.is_not(None),
                EvidenceRelation.reviewer_status != "rejected",
            )
        ).all()
        passage_ids = {edge.passage_id for edge in relations if edge.passage_id}
        rows = db.execute(
            select(Passage, Paper.title, Paper.doi)
            .join(PaperVersion, Passage.paper_version_id == PaperVersion.id)
            .join(Paper, PaperVersion.paper_id == Paper.id)
            .where(Passage.id.in_(passage_ids), Paper.owner_user_id == current_user.id)
            .order_by(Passage.page_number.asc().nullsfirst(), Passage.char_start.asc().nullsfirst())
        ).all() if passage_ids else []
        passages = [
            {
                "id": passage.id,
                "paper_title": title,
                "doi": doi,
                "page_number": passage.page_number,
                "section_title": passage.section_title,
                "text": passage.text[:8000],
            }
            for passage, title, doi in rows[:6]
        ]
        if not passages:
            skipped_count += 1
            results.append({
                "claim_id": claim.id,
                "status": "skipped",
                "reason": "No accessible, non-rejected evidence passages were linked to this claim.",
            })
            continue

        previous = {"assessment": claim.assessment, "review_required": claim.review_required}
        change_context = {
            "source_event_id": source_event.id,
            "source_title": source_title,
            "event_type": source_event.event_type,
            "description": source_event.description,
            "source_url": source_event.source_url,
            "event_date": source_event.event_date.isoformat() if source_event.event_date else None,
            "observed_at": source_event.observed_at.isoformat(),
            "verification_status": source_event.verification_status,
            "interpretation": "Review context only; not proof that any dependent claim is false.",
        }
        try:
            verdict = await verify_claim_with_llm(
                claim_statement=claim.statement,
                claim_scope=claim.scope or {},
                passages=passages,
                api_key=api_key,
                api_base=api_base,
                model=model,
                source_change_context=change_context,
            )
        except Exception:
            skipped_count += 1
            results.append({
                "claim_id": claim.id,
                "status": "failed",
                "reason": "The verifier could not complete this claim. Its prior assessment was preserved.",
            })
            continue

        claim.assessment = verdict["verdict"]
        claim.review_required = True
        record_audit_event(
            db,
            actor_user_id=current_user.id,
            run_id=claim.run_id,
            target_entity_type="claim",
            target_entity_id=claim.id,
            action="claim.reverified_after_source_event",
            previous_value=previous,
            new_value={
                "assessment": claim.assessment,
                "review_required": True,
                "source_event_id": source_event.id,
                "source_verification_status": source_event.verification_status,
                "evidence_passage_ids": verdict["evidence_passage_ids"],
                "rationale": verdict["rationale"],
                "uncertainty_notes": verdict["uncertainty_notes"],
                "model": model,
                "provenance_basis": "model_inferred",
            },
            reason="Researcher-requested targeted re-verification after a source event; human confirmation is still required.",
            resolution_status="needs_review",
        )
        rechecked_count += 1
        results.append({
            "claim_id": claim.id,
            "status": "reverified",
            "verdict": verdict["verdict"],
            "rationale": verdict["rationale"],
            "evidence_passage_ids": verdict["evidence_passage_ids"],
            "uncertainty_notes": verdict["uncertainty_notes"],
            "review_required": True,
        })

    db.commit()
    return {
        "event_id": source_event.id,
        "event_type": source_event.event_type,
        "source_verification_status": source_event.verification_status,
        "rechecked_count": rechecked_count,
        "skipped_count": skipped_count,
        "results": results,
        "note": "These are model-assisted reassessments, not proof of scientific truth. Claims remain flagged for human review. Unverified source events are not treated as confirmed corrections or retractions.",
    }


@router.get("/sources/papers/{paper_id}/events", response_model=list[SourceEventRead])
def list_source_events(paper_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[SourceEvent]:
    if db.scalar(select(Paper.id).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id)) is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return list(db.scalars(select(SourceEvent).where(SourceEvent.paper_id == paper_id).order_by(SourceEvent.observed_at.desc())).all())
