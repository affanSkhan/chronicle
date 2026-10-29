import asyncio
from types import SimpleNamespace

def test_create_and_get_demo_run(client) -> None:
    created = client.post(
        "/api/v1/research/runs",
        json={"question": "What are the limits of scientific RAG?", "mode": "deep", "max_sources": 8},
    )
    assert created.status_code == 201
    run = created.json()
    assert run["question"] == "What are the limits of scientific RAG?"
    assert run["status"] == "queued"
    assert run["demo"] is True

    fetched = client.get(f"/api/v1/research/runs/{run['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == run["id"]


def test_create_run_rejects_too_short_question(client) -> None:
    response = client.post("/api/v1/research/runs", json={"question": "short"})
    assert response.status_code == 422


def test_unknown_run_is_404(client) -> None:
    response = client.get("/api/v1/research/runs/not-a-real-id")
    assert response.status_code == 404


from datetime import datetime, timezone

from app.api import routes as research_routes
from app.models.entities import ResearchRun
from app.services import research_pipeline
from conftest import TestingSessionLocal


def _create_run(client, question: str = "How should Chronicle support lifecycle operations?") -> str:
    response = client.post("/api/v1/research/runs", json={
        "question": question,
        "mode": "deep",
        "max_sources": 4,
        "execute": False,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_cancel_queued_run_is_terminal_and_audited(client) -> None:
    run_id = _create_run(client)
    response = client.post(f"/api/v1/research/runs/{run_id}/cancel")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "cancelled"
    assert payload["cancelled_at"] is not None

    repeated = client.post(f"/api/v1/research/runs/{run_id}/cancel")
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "cancelled"

    audit = client.get(f"/api/v1/evidence/runs/{run_id}/audit")
    assert audit.status_code == 200, audit.text
    assert any(item["action"] == "research_run.cancelled" for item in audit.json()["events"])


def test_retry_failed_run_creates_new_linked_run_and_audit(client, monkeypatch) -> None:
    run_id = _create_run(client)
    with TestingSessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        run.status = "failed"
        run.demo = False
        run.error_message = "Provider request failed."
        db.commit()

    executed = []

    async def fake_execute(run_to_execute: str) -> None:
        executed.append(run_to_execute)

    monkeypatch.setattr(research_routes, "execute_research_run", fake_execute)
    response = client.post(f"/api/v1/research/runs/{run_id}/retry")
    assert response.status_code == 201, response.text
    retry = response.json()
    assert retry["id"] != run_id
    assert retry["retry_of_run_id"] == run_id
    assert retry["status"] == "queued"
    assert retry["question"] == "How should Chronicle support lifecycle operations?"
    assert retry["mode"] == "deep"
    assert retry["max_sources"] == 4
    assert executed == [retry["id"]]

    audit = client.get(f"/api/v1/evidence/runs/{retry['id']}/audit")
    assert audit.status_code == 200, audit.text
    assert any(item["action"] == "research_run.retried" for item in audit.json()["events"])


def test_retry_rejects_non_retryable_run_state(client) -> None:
    run_id = _create_run(client)
    response = client.post(f"/api/v1/research/runs/{run_id}/retry")
    assert response.status_code == 409, response.text


def test_running_provider_search_cancels_cooperatively(monkeypatch, client) -> None:
    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        research_pipeline,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None, openai_api_base="https://api.openai.com/v1", openai_model=""),
    )
    run_id = _create_run(client, "How should Chronicle cancel an in-flight provider search?")

    async def slow_search(question: str, limit: int = 10, provider: str = "all") -> dict:
        await asyncio.sleep(6)
        return {"query": question, "providers_requested": provider, "provider_errors": {}, "results": []}

    monkeypatch.setattr(research_pipeline, "search_papers", slow_search)

    async def execute_and_request_cancel() -> None:
        task = asyncio.create_task(research_pipeline.execute_research_run(run_id))
        await asyncio.sleep(0.2)
        with TestingSessionLocal() as db:
            run = db.get(ResearchRun, run_id)
            run.status = "cancel_requested"
            run.cancel_requested_at = datetime.now(timezone.utc)
            db.commit()
        await asyncio.wait_for(task, timeout=3)

    asyncio.run(execute_and_request_cancel())
    with TestingSessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        assert run.status == "cancelled"
        assert run.cancel_requested_at is not None
        assert run.cancelled_at is not None
        assert run.demo is False


def test_queue_mode_persists_run_without_inline_execution(client, monkeypatch) -> None:
    monkeypatch.setattr(research_routes, "get_settings", lambda: SimpleNamespace(research_execution_mode="queue"))
    executed = []

    async def fake_execute(run_id: str) -> None:
        executed.append(run_id)

    monkeypatch.setattr(research_routes, "execute_research_run", fake_execute)
    response = client.post("/api/v1/research/runs", json={
        "question": "How should queued research runs persist across API process restarts?",
        "mode": "deep",
        "execute": True,
    })
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "queued"
    assert response.json()["demo"] is False
    assert executed == []
