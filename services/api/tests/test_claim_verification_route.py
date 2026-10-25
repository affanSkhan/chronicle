import fitz
from types import SimpleNamespace

from app.api import evidence as evidence_api


def _pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def _claim_with_passage(client) -> tuple[str, str]:
    run = client.post(
        "/api/v1/research/runs",
        json={"question": "Does evidence traceability improve review quality?", "mode": "academic"},
    )
    assert run.status_code == 201, run.text

    upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("study.pdf", _pdf_bytes("The study reports better traceability for reviewed evidence records."), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    paper_id = upload.json()["paper_id"]
    passages = client.get(f"/api/v1/documents/papers/{paper_id}/passages")
    assert passages.status_code == 200, passages.text
    passage_id = passages.json()["passages"][0]["id"]

    claim = client.post(
        "/api/v1/evidence/claims",
        json={"run_id": run.json()["id"], "statement": "Traceability improves review quality."},
    )
    assert claim.status_code == 201, claim.text
    relation = client.post(
        f"/api/v1/evidence/claims/{claim.json()['id']}/relations",
        json={"passage_id": passage_id, "relation_type": "supports", "rationale": "The passage mentions improved traceability."},
    )
    assert relation.status_code == 201, relation.text
    return claim.json()["id"], run.json()["id"]


def test_verify_claim_endpoint_persists_verdict_and_audit(monkeypatch, client):
    claim_id, run_id = _claim_with_passage(client)
    monkeypatch.setattr(
        evidence_api,
        "get_settings",
        lambda: SimpleNamespace(
            openai_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
            openai_api_base="https://model.example/v1",
            openai_model="test-model",
        ),
    )

    async def fake_verify(**kwargs):
        assert kwargs["claim_statement"] == "Traceability improves review quality."
        assert len(kwargs["passages"]) == 1
        return {
            "verdict": "partially_supported",
            "rationale": "The supplied passage describes traceability but does not fully establish the claimed causal effect.",
            "evidence_passage_ids": [kwargs["passages"][0]["id"]],
            "context_note": "The source is a single passage from a user-uploaded PDF.",
            "uncertainty_notes": ["The document's broader study context was not assessed."],
        }

    monkeypatch.setattr(evidence_api, "verify_claim_with_llm", fake_verify)
    response = client.post(f"/api/v1/evidence/claims/{claim_id}/verify")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["verdict"] == "partially_supported"
    assert result["review_required"] is True
    assert result["reviewer_status"] == "needs_review"
    assert result["provenance_basis"] == "model_inferred"
    assert len(result["evidence_passage_ids"]) == 1
    assert "not proof of scientific truth" in result["notice"]

    claims = client.get(f"/api/v1/evidence/runs/{run_id}/claims")
    assert claims.status_code == 200, claims.text
    persisted = next(item for item in claims.json() if item["id"] == claim_id)
    assert persisted["assessment"] == "partially_supported"
    assert persisted["review_required"] is True

    audit = client.get(f"/api/v1/evidence/runs/{run_id}/audit")
    assert audit.status_code == 200, audit.text
    event = next(item for item in audit.json()["events"] if item["action"] == "claim.citation_verification_completed")
    assert event["resolution_status"] == "needs_review"
    assert event["new_value"]["provenance_basis"] == "model_inferred"


def test_verify_claim_without_configured_model_does_not_change_claim(monkeypatch, client):
    claim_id, run_id = _claim_with_passage(client)
    monkeypatch.setattr(
        evidence_api,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None, openai_model="", openai_api_base="https://api.openai.com/v1"),
    )

    response = client.post(f"/api/v1/evidence/claims/{claim_id}/verify")
    assert response.status_code == 503, response.text
    claims = client.get(f"/api/v1/evidence/runs/{run_id}/claims")
    persisted = next(item for item in claims.json() if item["id"] == claim_id)
    assert persisted["assessment"] == "unassessed"
    assert persisted["review_required"] is False
