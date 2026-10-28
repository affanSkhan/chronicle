import asyncio
from types import SimpleNamespace

import fitz

from app.services import research_pipeline
from conftest import TestingSessionLocal


def _pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def test_selected_uploaded_pdf_flows_into_claims_report_graph_and_passport(monkeypatch, client) -> None:
    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(research_pipeline, "get_settings", lambda: SimpleNamespace(enable_pdf_ocr=False))
    monkeypatch.setattr(
        research_pipeline,
        "get_llm_config",
        lambda settings: ("test-key", "https://model.example/v1", "test-model"),
    )

    full_text = (
        "The controlled study used 240 participants across two cohorts. "
        "A later correction changed the outcome definition and required downstream evidence review."
    )
    uploaded = client.post(
        "/api/v1/documents/upload",
        files={"file": ("temporal-study.pdf", _pdf_bytes(full_text), "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    paper_id = uploaded.json()["paper_id"]
    passage_response = client.get(f"/api/v1/documents/papers/{paper_id}/passages")
    assert passage_response.status_code == 200, passage_response.text
    pdf_passage_id = passage_response.json()["passages"][0]["id"]

    async def fake_search_papers(question: str, limit: int = 10, provider: str = "all") -> dict:
        return {
            "query": question,
            "providers_requested": provider,
            "provider_errors": {},
            "results": [{
                "provider": "crossref",
                "external_id": "10.5555/abstract-only-test",
                "doi": "10.5555/abstract-only-test",
                "title": "An abstract-only source",
                "authors": ["Example Author"],
                "abstract": "Abstract metadata provides background on evidence provenance and review.",
                "publication_year": 2025,
                "publisher": "Example Publisher",
                "landing_url": "https://doi.org/10.5555/abstract-only-test",
            }],
        }

    async def fake_extract_claims_from_passages(question: str, passages: list[dict], api_key: str, api_base: str, model: str) -> list[dict]:
        matching = next((item for item in passages if item["id"] == pdf_passage_id), None)
        assert matching is not None, "The selected PDF passage must reach the model extraction context."
        assert matching["page_number"] == 1
        assert "240 participants" in matching["text"]
        return [{
            "statement": "The study used 240 participants across two cohorts.",
            "scope": {"population": "240 participants across two cohorts"},
            "uncertainty_notes": "Extracted from an uploaded PDF and requires researcher review.",
            "evidence": [{
                "passage_id": pdf_passage_id,
                "relation_type": "supports",
                "rationale": "The supplied page passage directly states the participant count.",
            }],
        }]

    async def fake_synthesize_evidence(question: str, passages: list[dict], api_key: str, api_base: str, model: str) -> dict:
        matching = next((item for item in passages if item["id"] == pdf_passage_id), None)
        assert matching is not None, "Synthesis must receive the selected PDF passage."
        return {
            "executive_summary": "The uploaded document describes a controlled study and a correction event.",
            "findings": [{
                "statement": "The study used 240 participants across two cohorts.",
                "evidence_passage_ids": [pdf_passage_id],
                "relation_type": "supports",
                "context_note": "Extracted from the uploaded PDF; reviewer confirmation is required.",
            }],
            "study_characterizations": [],
            "disagreements": [],
            "limitations": ["Only selected passages were supplied to the model."],
            "candidate_research_questions": [],
            "research_opportunities": [],
            "uncertainty_statement": "This is model-assisted synthesis and is not a scientific truth guarantee.",
        }

    monkeypatch.setattr(research_pipeline, "search_papers", fake_search_papers)
    monkeypatch.setattr(research_pipeline, "extract_claims_from_passages", fake_extract_claims_from_passages)
    monkeypatch.setattr(research_pipeline, "synthesize_evidence", fake_synthesize_evidence)

    created = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How do source corrections affect evidence from study cohorts?",
            "mode": "academic",
            "max_sources": 5,
            "execute": False,
            "source_paper_ids": [paper_id],
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    # Execute directly with the isolated DB to keep the test deterministic.
    asyncio.run(research_pipeline.execute_research_run(run_id))

    run_result = client.get(f"/api/v1/research/runs/{run_id}")
    assert run_result.status_code == 200
    assert run_result.json()["status"] == "completed"
    assert run_result.json()["progress_percent"] == 100
    assert run_result.json()["stage_statuses"]["report_commit"] == "completed"

    reports = client.get(f"/api/v1/evidence/runs/{run_id}/reports")
    assert reports.status_code == 200
    snapshot = reports.json()[0]["evidence_snapshot"]
    assert paper_id in snapshot["source_paper_ids"]
    assert pdf_passage_id in snapshot["passage_ids"]
    assert snapshot["context_selection"]["selected_uploaded_pdf_passages"] >= 1

    graph = client.get(f"/api/v1/evidence/runs/{run_id}/graph")
    assert graph.status_code == 200
    assert any(node.get("id") == f"passage:{pdf_passage_id}" or node.get("id") == pdf_passage_id for node in graph.json()["nodes"])
    assert any(node.get("type") == "claim" and "240 participants" in node.get("label", "") for node in graph.json()["nodes"])

    passport = client.get(f"/api/v1/evidence/runs/{run_id}/passport?format=json")
    assert passport.status_code == 200
    exported = passport.json()
    assert any(paper["id"] == paper_id and paper["source_provider"] == "upload" for paper in exported["papers"])
    assert any(
        relation.get("passage", {}).get("id") == pdf_passage_id
        for claim in exported["claims"]
        for relation in claim["evidence_relations"]
    )


def test_research_run_rejects_uploaded_pdf_owned_by_another_account(client) -> None:
    uploaded = client.post(
        "/api/v1/documents/upload",
        files={"file": ("private.pdf", _pdf_bytes("Private research data must remain owner scoped."), "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    paper_id = uploaded.json()["paper_id"]

    second = client.post(
        "/api/v1/auth/register",
        json={"email": "second-user@example.test", "password": "another-secure-password"},
    )
    assert second.status_code == 201, second.text
    client.headers.update({"Authorization": f"Bearer {second.json()['access_token']}"})
    rejected = client.post(
        "/api/v1/research/runs",
        json={
            "question": "Can a second user access a private PDF?",
            "mode": "deep",
            "execute": False,
            "source_paper_ids": [paper_id],
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert "uploaded document in your own library" in rejected.json()["detail"]
