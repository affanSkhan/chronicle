"""Scheduled source-status checks for papers opted into monitoring.

The worker stores metadata signals and hashes, but never creates a SourceEvent,
marks a paper retracted, or invalidates claims automatically. Monitoring is a
review prompt, not a substitute for publisher verification.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import Paper, SourceStatusCheck
from app.services.audit import record_audit_event
from app.services.source_status import fetch_paper_status_signals, stable_signal_fingerprint


def _result_hash(signals: list[dict[str, Any]]) -> str:
    payload = stable_signal_fingerprint(signals)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _outcome(doi: str | None, provider_states: dict[str, str]) -> str:
    if not doi:
        return "no_doi"
    states = list(provider_states.values())
    if not states or all(state in {"unavailable", "skipped_no_doi"} for state in states):
        return "unavailable"
    if any(state == "unavailable" for state in states):
        return "partial"
    return "ok"


async def check_one_monitored_paper(paper_id: str) -> dict[str, Any] | None:
    """Check one currently monitored paper and persist the result."""
    with SessionLocal() as db:
        paper = db.get(Paper, paper_id)
        if paper is None or not paper.monitoring_enabled:
            return None
        doi = paper.doi
        interval = max(60, paper.monitor_interval_minutes)

    checked_at = datetime.now(timezone.utc)
    error_message = None
    try:
        result = await fetch_paper_status_signals(doi or "")
        provider_states = result.get("providers", {})
        signals = result.get("signals", [])
        outcome = _outcome(doi, provider_states)
        if outcome in {"unavailable", "partial"}:
            error_message = "One or more metadata providers were unavailable; this check may be incomplete."
    except Exception:
        provider_states = {"crossref": "unavailable", "openalex": "unavailable"}
        signals = []
        outcome = "no_doi" if not doi else "failed"
        error_message = "Source-status check failed. See server logs for provider diagnostics."

    current_hash = _result_hash(signals)
    with SessionLocal() as db:
        paper = db.get(Paper, paper_id)
        # Monitoring might have been disabled while network calls were in flight.
        if paper is None or not paper.monitoring_enabled:
            return None

        previous = db.scalar(
            select(SourceStatusCheck)
            .where(SourceStatusCheck.paper_id == paper.id)
            .order_by(SourceStatusCheck.checked_at.desc())
        )
        previous_hash = previous.result_hash if previous else None
        complete_provider_result = any(state in {"ok", "not_found"} for state in provider_states.values())
        change_detected = bool(
            previous_hash is not None
            and complete_provider_result
            and outcome in {"ok", "partial"}
            and previous_hash != current_hash
        )

        check = SourceStatusCheck(
            paper_id=paper.id,
            checked_at=checked_at,
            trigger_type="scheduled",
            outcome=outcome,
            provider_states=provider_states,
            signals=signals,
            result_hash=current_hash,
            previous_result_hash=previous_hash,
            change_detected=change_detected,
            error_message=error_message,
        )
        db.add(check)
        paper.last_status_check_at = checked_at
        paper.next_status_check_at = checked_at + timedelta(minutes=interval)
        db.flush()
        record_audit_event(
            db,
            actor_user_id=None,
            run_id=None,
            target_entity_type="source_status_check",
            target_entity_id=check.id,
            action="source_status_check.scheduled_completed",
            previous_value={
                "result_hash": previous_hash,
                "next_status_check_at": None,
            },
            new_value={
                "result_hash": current_hash,
                "change_detected": change_detected,
                "outcome": outcome,
                "signal_count": len(signals),
                "next_status_check_at": paper.next_status_check_at.isoformat(),
            },
            reason="Scheduled provider metadata check completed. Signals remain pending human review.",
            resolution_status="needs_review" if change_detected or signals else "recorded",
        )
        db.commit()
        return {
            "paper_id": paper.id,
            "status_check_id": check.id,
            "outcome": outcome,
            "change_detected": change_detected,
            "signal_count": len(signals),
            "next_status_check_at": paper.next_status_check_at.isoformat() if paper.next_status_check_at else None,
        }


async def run_due_status_checks(batch_size: int | None = None) -> list[dict[str, Any]]:
    settings = get_settings()
    limit = batch_size or settings.source_monitor_batch_size
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        due_ids = list(db.scalars(
            select(Paper.id)
            .where(
                Paper.monitoring_enabled.is_(True),
                or_(Paper.next_status_check_at.is_(None), Paper.next_status_check_at <= now),
            )
            .order_by(Paper.next_status_check_at.asc().nullsfirst(), Paper.last_status_check_at.asc().nullsfirst())
            .limit(max(1, min(limit, 100)))
        ).all())

    results = []
    for paper_id in due_ids:
        result = await check_one_monitored_paper(paper_id)
        if result is not None:
            results.append(result)
    return results


async def scheduled_monitor_loop() -> None:
    """Single-process polling loop. Use a distributed worker/leader lock for multiple replicas."""
    settings = get_settings()
    poll_seconds = max(15, settings.source_monitor_poll_seconds)
    while True:
        try:
            await run_due_status_checks()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not log provider payloads or paper contents. The API remains up;
            # failed checks are retried next poll because they are left due.
            pass
        await asyncio.sleep(poll_seconds)
