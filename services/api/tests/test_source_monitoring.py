import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app.models.entities import Paper, SourceEvent, SourceStatusCheck
from app.services import status_monitor
from conftest import TestingSessionLocal


def add_paper(client, doi: str = "10.5555/monitoring-test") -> dict:
    response = client.post(
        "/api/v1/sources/papers",
        json={
            "provider": "manual",
            "external_id": doi,
            "doi": doi,
            "title": "Monitoring Test Paper",
            "authors": ["Example Author"],
            "abstract": "An abstract for testing monitored source metadata.",
            "publication_year": 2025,
            "landing_url": f"https://doi.org/{doi}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_manual_status_check_is_persisted_and_owner_scoped(monkeypatch, client) -> None:
    paper = add_paper(client)

    async def fake_status(doi: str) -> dict:
        assert doi == "10.5555/monitoring-test"
        return {
            "providers": {"crossref": "ok", "openalex": "ok"},
            "signals": [{
                "provider": "crossref",
                "event_type": "correction",
                "update_type": "correction",
                "description": "A correction notice may affect how this study is interpreted.",
                "source_url": "https://publisher.example/correction",
                "verification_status": "metadata_confirmed",
                "metadata": {},
            }],
            "note": "Fake provider result for a deterministic test.",
        }

    monkeypatch.setattr("app.api.sources.fetch_paper_status_signals", fake_status)
    response = client.post(f"/api/v1/sources/papers/{paper['id']}/status-check")
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["trigger_type"] == "manual"
    assert result["outcome"] == "ok"
    assert result["change_detected"] is False  # First observation establishes the baseline.
    assert len(result["signals"]) == 1

    history = client.get("/api/v1/sources/status-checks")
    assert history.status_code == 200, history.text
    assert history.json()["count"] == 1
    assert history.json()["checks"][0]["id"] == result["id"]

    per_paper = client.get(f"/api/v1/sources/papers/{paper['id']}/status-checks")
    assert per_paper.status_code == 200
    assert per_paper.json()["count"] == 1

    # Metadata preview remains read-only: a signal is not a SourceEvent.
    with TestingSessionLocal() as db:
        assert db.scalar(select(SourceEvent).where(SourceEvent.paper_id == paper["id"])) is None


def test_monitor_configuration_and_scheduled_change_detection(monkeypatch, client) -> None:
    paper = add_paper(client, "10.5555/scheduled-monitor-test")

    enabled = client.patch(
        f"/api/v1/sources/papers/{paper['id']}/monitoring",
        json={"enabled": True, "interval_minutes": 60},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["monitoring_enabled"] is True
    assert enabled.json()["monitor_interval_minutes"] == 60
    assert enabled.json()["next_status_check_at"]

    monkeypatch.setattr(status_monitor, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        status_monitor,
        "get_settings",
        lambda: SimpleNamespace(source_monitor_batch_size=20, source_monitor_poll_seconds=60),
    )

    state = {"source_url": "https://publisher.example/notice-v1"}

    async def fake_status(doi: str) -> dict:
        return {
            "providers": {"crossref": "ok", "openalex": "not_found"},
            "signals": [{
                "provider": "crossref",
                "event_type": "expression_of_concern",
                "update_type": "expression-of-concern",
                "description": "A publisher notice needs review.",
                "source_url": state["source_url"],
                "verification_status": "metadata_confirmed",
                "metadata": {},
            }],
            "note": "Fake provider response.",
        }

    monkeypatch.setattr(status_monitor, "fetch_paper_status_signals", fake_status)
    first = asyncio.run(status_monitor.run_due_status_checks())
    assert len(first) == 1
    assert first[0]["outcome"] == "ok"
    assert first[0]["change_detected"] is False

    with TestingSessionLocal() as db:
        stored_paper = db.get(Paper, paper["id"])
        stored_paper.next_status_check_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    state["source_url"] = "https://publisher.example/notice-v2"
    second = asyncio.run(status_monitor.run_due_status_checks())
    assert len(second) == 1
    assert second[0]["change_detected"] is True

    history = client.get("/api/v1/sources/papers/" + paper["id"] + "/status-checks").json()
    assert history["count"] == 2
    assert history["checks"][0]["trigger_type"] == "scheduled"
    assert history["checks"][0]["change_detected"] is True
    with TestingSessionLocal() as db:
        checks = db.scalars(select(SourceStatusCheck).where(SourceStatusCheck.paper_id == paper["id"])).all()
        assert len(checks) == 2
        assert db.scalar(select(SourceEvent).where(SourceEvent.paper_id == paper["id"])) is None

    disabled = client.patch(
        f"/api/v1/sources/papers/{paper['id']}/monitoring",
        json={"enabled": False, "interval_minutes": 60},
    )
    assert disabled.status_code == 200
    assert disabled.json()["monitoring_enabled"] is False
    assert disabled.json()["next_status_check_at"] is None


def test_monitor_worker_ignores_disabled_papers(monkeypatch, client) -> None:
    paper = add_paper(client, "10.5555/disabled-monitor-test")
    monkeypatch.setattr(status_monitor, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        status_monitor,
        "get_settings",
        lambda: SimpleNamespace(source_monitor_batch_size=20, source_monitor_poll_seconds=60),
    )

    async def never_fetch(doi: str) -> dict:
        raise AssertionError("Disabled paper must not be queried.")

    monkeypatch.setattr(status_monitor, "fetch_paper_status_signals", never_fetch)
    assert asyncio.run(status_monitor.run_due_status_checks()) == []
    with TestingSessionLocal() as db:
        assert db.scalar(select(SourceStatusCheck).where(SourceStatusCheck.paper_id == paper["id"])) is None


def test_manual_provider_outage_is_not_misclassified_as_source_change(monkeypatch, client) -> None:
    paper = add_paper(client, "10.5555/provider-outage-test")
    state = {"available": True}

    async def fake_status(doi: str) -> dict:
        if state["available"]:
            return {
                "providers": {"crossref": "ok", "openalex": "not_found"},
                "signals": [{
                    "provider": "crossref",
                    "event_type": "correction",
                    "update_type": "correction",
                    "description": "A correction signal was previously reported.",
                    "source_url": "https://publisher.example/correction",
                    "verification_status": "metadata_confirmed",
                    "metadata": {},
                }],
                "note": "Initial complete check.",
            }
        return {
            "providers": {"crossref": "unavailable", "openalex": "unavailable"},
            "signals": [],
            "note": "Both public metadata providers were unavailable.",
        }

    monkeypatch.setattr("app.api.sources.fetch_paper_status_signals", fake_status)
    first = client.post(f"/api/v1/sources/papers/{paper['id']}/status-check")
    assert first.status_code == 201
    assert first.json()["change_detected"] is False

    state["available"] = False
    second = client.post(f"/api/v1/sources/papers/{paper['id']}/status-check")
    assert second.status_code == 201
    assert second.json()["outcome"] == "unavailable"
    assert second.json()["change_detected"] is False
    assert "unavailable" in second.json()["note"].lower()
