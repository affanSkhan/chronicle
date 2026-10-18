import asyncio
from types import SimpleNamespace

from app.services import research_pipeline
from conftest import TestingSessionLocal


def test_research_pipeline_persists_metadata_report_and_evidence(monkeypatch, client) -> None:
    # The integration test exercises the complete pipeline while keeping the
    # provider response deterministic and avoiding external API credentials.
    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        research_pipeline,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None, openai_api_base="https://api.openai.com/v1", openai_model=""),
    )

    async def fake_search_papers(question: str, limit: int = 10, provider: str = "all") -> dict:
        assert question == "How does evidence provenance improve research reliability?"
        return {
            "query": question,
            "providers_requested": provider,
            "provider_errors": {},
            "results": [
                {
                    "provider": "crossref",
                    "external_id": "10.5555/chronicle-test-1",
                    "doi": "10.5555/chronicle-test-1",
                    "title": "Evidence Provenance in Scientific Workflows",
                    "authors": ["Test Author"],
                    "abstract": "Provenance makes evidence lineage inspectable and supports auditability.",
                    "publication_year": 2024,
                    "publisher": "Example Publisher",
                    "landing_url": "https://doi.org/10.5555/chronicle-test-1",
                },
                {
                    "provider": "openalex",
                    "external_id": "https://openalex.org/W123456789",
                    "doi": None,
                    "title": "Temporal Research State and Source Updates",
                    "authors": ["Second Test Author"],
                    "abstract": "Versioned evidence records support impact analysis when source status changes.",
                    "publication_year": 2025,
                    "publisher": "Example Journal",
                    "landing_url": "https://openalex.org/W123456789",
                },
            ],
        }

    monkeypatch.setattr(research_pipeline, "search_papers", fake_search_papers)

    created = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How does evidence provenance improve research reliability?",
            "mode": "academic",
            "max_sources": 5,
            "execute": False,
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    assert created.json()["demo"] is True

    asyncio.run(research_pipeline.execute_research_run(run_id))

    run_response = client.get(f"/api/v1/research/runs/{run_id}")
    assert run_response.status_code == 200, run_response.text
    run = run_response.json()
    assert run["status"] == "completed"
    assert run["demo"] is False

    reports_response = client.get(f"/api/v1/evidence/runs/{run_id}/reports")
    assert reports_response.status_code == 200, reports_response.text
    reports = reports_response.json()
    assert len(reports) == 1
    report = reports[0]
    assert report["title"] == "Academic Discovery Snapshot"
    assert "Evidence Provenance in Scientific Workflows" in report["content_markdown"]
    assert "Model synthesis skipped" in report["content_markdown"]
    assert report["evidence_snapshot"]["claim_verification_completed"] is False

    graph_response = client.get(f"/api/v1/evidence/runs/{run_id}/graph")
    assert graph_response.status_code == 200, graph_response.text
    graph = graph_response.json()
    assert any(node["type"] == "paper" and node["label"] == "Evidence Provenance in Scientific Workflows" for node in graph["nodes"])
    assert any(node["type"] == "passage" and "Provenance makes evidence lineage" in node["label"] for node in graph["nodes"])

    passport = client.get(f"/api/v1/evidence/runs/{run_id}/passport?format=json")
    assert passport.status_code == 200, passport.text
    passport_papers = passport.json()["papers"]
    assert len(passport_papers) == 2
    assert any(paper["doi"] == "10.5555/chronicle-test-1" for paper in passport_papers)
