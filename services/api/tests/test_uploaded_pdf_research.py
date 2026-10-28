import asyncio
from types import SimpleNamespace

import fitz

from app.services import research_pipeline


def _pdf_bytes() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((60, 80), "Uniquebeta neural retrieval evaluation compares citation provenance and exact source passage coverage.")
    page.insert_text((60, 115), "The study records page-anchored evidence and reports limits of abstract-only discovery.")
    payload = document.tobytes()
    document.close()
    return payload


def test_uploaded_pdf_is_a_real_research_input_and_its_page_passage_is_snapshotted(monkeypatch, client) -> None:
    from conftest import TestingSessionLocal
    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        research_pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            llm_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
            llm_api_base="https://model.example/v1",
            llm_model="test-model",
            openai_api_key=None,
            openai_api_base="https://api.openai.com/v1",
            openai_model="",
        ),
    )

    upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("local-review.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    paper_id = upload.json()["paper_id"]

    async def fake_search_papers(question: str, limit: int = 10, provider: str = "all") -> dict:
        return {
            "query": question,
            "providers_requested": provider,
            "provider_errors": {},
            "results": [{
                "provider": "crossref",
                "external_id": "10.5555/remote-unrelated",
                "doi": "10.5555/remote-unrelated",
                "title": "Remote paper about unrelated ocean sensors",
                "authors": ["Example Author"],
                "abstract": "Ocean temperature sensors estimate salinity and water pressure.",
                "publication_year": 2023,
                "publisher": "Example Publisher",
                "landing_url": "https://doi.org/10.5555/remote-unrelated",
            }],
        }

    async def fake_extract_claims_from_passages(question, passages, api_key, api_base, model):
        assert any("Uniquebeta" in passage["text"] for passage in passages)
        assert any(passage.get("page_number") == 1 for passage in passages if "Uniquebeta" in passage["text"])
        return []

    async def fake_synthesize_evidence(question, passages, api_key, api_base, model):
        assert any("Uniquebeta" in passage["text"] for passage in passages)
        first_id = next(passage["id"] for passage in passages if "Uniquebeta" in passage["text"])
        return {
            "executive_summary": "The uploaded PDF has relevant page-anchored evidence for this question.",
            "findings": [{
                "statement": "The selected uploaded PDF discusses citation provenance.",
                "evidence_passage_ids": [first_id],
                "relation_type": "qualifies",
                "context_note": "A human reviewer must inspect the original page.",
            }],
            "study_characterizations": [],
            "disagreements": [],
            "limitations": ["This test source is a single uploaded PDF."],
            "candidate_research_questions": [],
            "research_opportunities": [],
            "uncertainty_statement": "This is a deterministic integration test fixture.",
            "input_passage_ids": [first_id],
            "validated_source_references": True,
            "human_review_required": True,
        }

    monkeypatch.setattr(research_pipeline, "search_papers", fake_search_papers)
    monkeypatch.setattr(research_pipeline, "extract_claims_from_passages", fake_extract_claims_from_passages)
    monkeypatch.setattr(research_pipeline, "synthesize_evidence", fake_synthesize_evidence)

    created = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How does Uniquebeta citation provenance evidence lineage evaluation work?",
            "mode": "academic",
            "max_sources": 4,
            "uploaded_paper_ids": [paper_id],
            "execute": False,
        },
    )
    assert created.status_code == 201, created.text

    asyncio.run(research_pipeline.execute_research_run(created.json()["id"]))

    reports = client.get(f"/api/v1/evidence/runs/{created.json()['id']}/reports")
    assert reports.status_code == 200, reports.text
    report = reports.json()[0]
    snapshot = report["evidence_snapshot"]
    assert paper_id in snapshot["paper_ids"]
    assert snapshot["uploaded_pdf_passage_ids"]
    assert "Selected uploaded-PDF passages" in report["content_markdown"]
    assert "Uniquebeta" in report["content_markdown"]


def test_selected_pdf_ids_are_owner_scoped(client) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("private.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    foreign_paper_id = upload.json()["paper_id"]

    other_account = client.post(
        "/api/v1/auth/register",
        json={"email": "another-user@example.test", "password": "another-test-password-123"},
    )
    assert other_account.status_code == 201, other_account.text
    access_token = other_account.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {access_token}"

    response = client.post(
        "/api/v1/research/runs",
        json={
            "question": "Can another user access this private uploaded PDF?",
            "mode": "academic",
            "uploaded_paper_ids": [foreign_paper_id],
            "execute": False,
        },
    )
    assert response.status_code == 404, response.text
