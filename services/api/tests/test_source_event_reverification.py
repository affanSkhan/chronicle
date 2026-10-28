import fitz

from app.api import sources as sources_api


def _pdf_bytes() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "The intervention reports a measured improvement in review quality.")
    payload = document.tobytes()
    document.close()
    return payload


def _claim_and_source_event(client, verification_status="human_verified"):
    run = client.post(
        "/api/v1/research/runs",
        json={"question": "Does the intervention improve review quality?", "mode": "academic"},
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]

    upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("study.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    paper_id = upload.json()["paper_id"]
    passages = client.get(f"/api/v1/documents/papers/{paper_id}/passages")
    assert passages.status_code == 200, passages.text
    passage_id = passages.json()["passages"][0]["id"]

    claim = client.post(
        "/api/v1/evidence/claims",
        json={"run_id": run_id, "statement": "The intervention improves review quality."},
    )
    assert claim.status_code == 201, claim.text
    claim_id = claim.json()["id"]
    link = client.post(
        f"/api/v1/evidence/claims/{claim_id}/relations",
        json={"passage_id": passage_id, "relation_type": "supports", "rationale": "The passage reports an improvement."},
    )
    assert link.status_code == 201, link.text

    event = client.post(
        f"/api/v1/sources/papers/{paper_id}/events",
        json={
            "event_type": "correction",
            "description": "Publisher correction changes the reported outcome estimate.",
            "source_url": "https://publisher.example/correction",
            "verification_status": verification_status,
        },
    )
    assert event.status_code == 201, event.text
    assert claim_id in event.json()["impact"]["affected_claim_ids"]
    return run_id, claim_id, event.json()["event"]["id"]


def test_source_event_reverification_records_new_verdict_and_keeps_human_review(monkeypatch, client):
    run_id, claim_id, event_id = _claim_and_source_event(client)
    monkeypatch.setattr(sources_api, "get_llm_config", lambda settings: ("test-key", "https://model.example/v1", "test-model"))

    async def fake_verify(**kwargs):
        assert kwargs["claim_statement"] == "The intervention improves review quality."
        assert len(kwargs["passages"]) == 1
        assert kwargs["source_change_context"]["event_type"] == "correction"
        assert kwargs["source_change_context"]["verification_status"] == "human_verified"
        return {
            "verdict": "partially_supported",
            "rationale": "The passage is consistent with the claim but does not independently assess the correction.",
            "evidence_passage_ids": [kwargs["passages"][0]["id"]],
            "context_note": "The source-update notice requires manual inspection.",
            "uncertainty_notes": ["The correction text is not part of the source passage supplied."],
        }

    monkeypatch.setattr(sources_api, "verify_claim_with_llm", fake_verify)
    response = client.post(f"/api/v1/sources/events/{event_id}/reverify-impacted-claims")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rechecked_count"] == 1
    assert payload["results"][0]["verdict"] == "partially_supported"
    assert payload["results"][0]["review_required"] is True

    claims = client.get(f"/api/v1/evidence/runs/{run_id}/claims")
    stored = next(item for item in claims.json() if item["id"] == claim_id)
    assert stored["assessment"] == "partially_supported"
    assert stored["review_required"] is True

    audit = client.get(f"/api/v1/evidence/runs/{run_id}/audit").json()["events"]
    saved = next(item for item in audit if item["action"] == "claim.reverified_after_source_event")
    assert saved["resolution_status"] == "needs_review"
    assert saved["new_value"]["source_event_id"] == event_id
    assert saved["new_value"]["source_verification_status"] == "human_verified"


def test_source_event_reverification_requires_model_configuration_without_mutation(monkeypatch, client):
    run_id, claim_id, event_id = _claim_and_source_event(client)
    monkeypatch.setattr(sources_api, "get_llm_config", lambda settings: ("", "https://model.example/v1", ""))

    response = client.post(f"/api/v1/sources/events/{event_id}/reverify-impacted-claims")
    assert response.status_code == 503, response.text
    claims = client.get(f"/api/v1/evidence/runs/{run_id}/claims")
    stored = next(item for item in claims.json() if item["id"] == claim_id)
    assert stored["assessment"] == "unassessed"
    assert stored["review_required"] is True


def test_source_event_reverification_is_owner_scoped(client):
    _, _, event_id = _claim_and_source_event(client)
    other = client.post(
        "/api/v1/auth/register",
        json={"email": "source-reverify-other@example.test", "password": "different-test-password-123"},
    )
    assert other.status_code == 201, other.text
    access_token = other.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {access_token}"
    response = client.post(f"/api/v1/sources/events/{event_id}/reverify-impacted-claims")
    assert response.status_code == 404, response.text
