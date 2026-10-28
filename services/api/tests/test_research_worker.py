from datetime import datetime, timedelta, timezone

from app.models.entities import ResearchRun
from app.services import research_worker
from conftest import TestingSessionLocal


def _queued_run(*, demo: bool = False, config: dict | None = None) -> str:
    from sqlalchemy import select
    from app.models.entities import User

    with TestingSessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "fixture-user@example.test"))
        assert user is not None
        run = ResearchRun(
            owner_user_id=user.id,
            project_id=None,
            question="How should worker claims survive process exits?",
            mode="deep",
            status="queued",
            max_sources=5,
            demo=demo,
            configuration=config or {},
        )
        db.add(run)
        db.commit()
        return run.id


def test_worker_claims_queued_executable_run_once(monkeypatch, client) -> None:
    monkeypatch.setattr(research_worker, "SessionLocal", TestingSessionLocal)
    run_id = _queued_run()
    assert research_worker.claim_next_run() == run_id
    assert research_worker.claim_next_run() is None
    with TestingSessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        assert run is not None
        assert run.status == "running"
        assert run.configuration["execution_worker"] == "database-worker"
        assert run.configuration["worker_heartbeat_at"]


def test_worker_does_not_claim_demo_request(monkeypatch, client) -> None:
    monkeypatch.setattr(research_worker, "SessionLocal", TestingSessionLocal)
    _queued_run(demo=True)
    assert research_worker.claim_next_run() is None


def test_worker_recovers_only_stale_database_worker_leases(monkeypatch, client) -> None:
    monkeypatch.setattr(research_worker, "SessionLocal", TestingSessionLocal)
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    stale_id = _queued_run(config={
        "execution_worker": "database-worker",
        "worker_claimed_at": old,
        "worker_heartbeat_at": old,
    })
    inline_id = _queued_run(config={"pipeline": "inline-run"})
    with TestingSessionLocal() as db:
        inline = db.get(ResearchRun, inline_id)
        inline.status = "running"
        db.commit()

    assert research_worker.recover_stale_runs(stale_after_seconds=30) == 1
    with TestingSessionLocal() as db:
        stale = db.get(ResearchRun, stale_id)
        inline = db.get(ResearchRun, inline_id)
        assert stale is not None and stale.status == "failed"
        assert "worker stopped" in (stale.error_message or "")
        assert inline is not None and inline.status == "running"


def test_pipeline_refuses_duplicate_inline_execution_of_running_run(monkeypatch, client) -> None:
    from app.services import research_pipeline

    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    run_id = _queued_run(config={"execution_worker": "database-worker"})
    with TestingSessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        run.status = "running"
        db.commit()
    import asyncio

    asyncio.run(research_pipeline.execute_research_run(run_id))
    with TestingSessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        assert run is not None and run.status == "running"
