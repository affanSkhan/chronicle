"""PostgreSQL-backed worker for durable queued Chronicle research runs.

This worker is opt-in. Configure RESEARCH_EXECUTION_MODE=queue on the API and run
one or more copies of this module as a separate service. Queue rows persist in the
database; a claimed run whose worker heartbeat expires is marked failed for explicit
retry rather than being silently lost or re-run from an unknown checkpoint.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import AuditEvent, ResearchRun
from app.services.audit import record_audit_event
from app.services.research_pipeline import execute_research_run

logger = logging.getLogger("chronicle.research_worker")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def claim_next_run() -> str | None:
    """Atomically claim one queued, executable run. SKIP LOCKED allows multiple workers."""
    now = _now()
    with SessionLocal() as db:
        run = db.scalar(
            select(ResearchRun)
            .where(ResearchRun.status == "queued", ResearchRun.demo.is_(False))
            .order_by(ResearchRun.created_at.asc(), ResearchRun.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if run is None:
            db.rollback()
            return None
        previous = {"status": run.status, "execution_worker": (run.configuration or {}).get("execution_worker")}
        run.status = "running"
        run.error_message = None
        run.configuration = {
            **(run.configuration or {}),
            "execution_worker": "database-worker",
            "worker_claimed_at": now.isoformat(),
            "worker_heartbeat_at": now.isoformat(),
            "worker_attempt": int((run.configuration or {}).get("worker_attempt", 0)) + 1,
        }
        record_audit_event(
            db,
            actor_user_id=None,
            run_id=run.id,
            target_entity_type="research_run",
            target_entity_id=run.id,
            action="research_run.worker_claimed",
            previous_value=previous,
            new_value={"status": "running", "execution_worker": "database-worker", "worker_claimed_at": now.isoformat()},
            reason="A database-backed worker claimed the persistent queued run.",
        )
        db.commit()
        return run.id


def recover_stale_runs(*, stale_after_seconds: int | None = None) -> int:
    """Fail only stale database-worker leases; do not touch inline or demo runs."""
    settings = get_settings()
    threshold = max(30, int(stale_after_seconds or settings.research_worker_stale_after_seconds))
    now = _now()
    changed = 0
    with SessionLocal() as db:
        runs = db.scalars(select(ResearchRun).where(ResearchRun.status == "running")).all()
        for run in runs:
            config = run.configuration if isinstance(run.configuration, dict) else {}
            if config.get("execution_worker") != "database-worker":
                continue
            heartbeat = _parse_time(config.get("worker_heartbeat_at")) or _parse_time(config.get("worker_claimed_at"))
            if heartbeat is not None and now - heartbeat < timedelta(seconds=threshold):
                continue
            previous = {
                "status": run.status,
                "worker_heartbeat_at": config.get("worker_heartbeat_at"),
                "worker_claimed_at": config.get("worker_claimed_at"),
            }
            run.status = "failed"
            run.error_message = "The research worker stopped before this run finalized. Retry starts a fresh run; the original history is preserved."
            run.configuration = {
                **config,
                "worker_recovery": {
                    "recovered_at": now.isoformat(),
                    "reason": "worker heartbeat expired",
                    "stale_after_seconds": threshold,
                },
            }
            record_audit_event(
                db,
                actor_user_id=None,
                run_id=run.id,
                target_entity_type="research_run",
                target_entity_id=run.id,
                action="research_run.worker_lease_expired",
                previous_value=previous,
                new_value={"status": "failed", "recovered_at": now.isoformat()},
                reason="The database-worker heartbeat expired; automatic resume is not safe because per-stage checkpoints are not persisted.",
                resolution_status="needs_review",
            )
            changed += 1
        if changed:
            db.commit()
        else:
            db.rollback()
    return changed


async def _heartbeat(run_id: str, *, interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(max(5, interval_seconds))
        with SessionLocal() as db:
            run = db.get(ResearchRun, run_id)
            if run is None or run.status not in {"running", "cancel_requested"}:
                return
            config = run.configuration if isinstance(run.configuration, dict) else {}
            if config.get("execution_worker") != "database-worker":
                return
            run.configuration = {**config, "worker_heartbeat_at": _now().isoformat()}
            db.commit()


async def execute_claimed_run(run_id: str) -> None:
    settings = get_settings()
    heartbeat_task = asyncio.create_task(
        _heartbeat(run_id, interval_seconds=settings.research_worker_heartbeat_seconds)
    )
    try:
        await execute_research_run(run_id, claimed_by_worker=True)
    except Exception:
        logger.exception("Unhandled exception while executing research run %s", run_id)
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


async def worker_loop() -> None:
    settings = get_settings()
    poll_seconds = max(1, int(settings.research_worker_poll_seconds))
    logger.info("Chronicle database worker started; poll interval=%ss", poll_seconds)
    while True:
        try:
            recover_stale_runs()
            run_id = claim_next_run()
            if run_id:
                await execute_claimed_run(run_id)
            else:
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Keep the service alive; never log research passage contents or credentials.
            logger.exception("Research worker loop failed; will retry")
            await asyncio.sleep(poll_seconds)


def main() -> None:
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
