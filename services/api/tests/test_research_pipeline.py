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
        assert question and len(question) >= 8  # query expansion is expected for mode-specific planning
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

    from app.models.entities import SourceStatusCheck
    with TestingSessionLocal() as db:
        check_paper_id = next(paper["id"] for paper in passport_papers if paper["doi"] == "10.5555/chronicle-test-1")
        db.add(SourceStatusCheck(
            paper_id=check_paper_id,
            trigger_type="scheduled",
            outcome="ok",
            provider_states={"crossref": "ok", "openalex": "ok"},
            signals=[{
                "provider": "crossref",
                "event_type": "correction",
                "description": "Candidate update notice for review.",
                "source_url": "https://example.org/status-notice",
            }],
            result_hash="a" * 64,
            previous_result_hash="b" * 64,
            change_detected=True,
        ))
        db.commit()
    passport = client.get(f"/api/v1/evidence/runs/{run_id}/passport?format=json").json()
    assert any(check["trigger_type"] == "scheduled" and check["change_detected"] for check in passport["source_status_checks"])
    assert any(signal["source_url"] == "https://example.org/status-notice" for check in passport["source_status_checks"] for signal in check["signals"])

    # A discovery report must be flagged when one of its source papers changes,
    # even if no model-derived claims were created for that run.
    paper_id = next(paper["id"] for paper in passport_papers if paper["doi"] == "10.5555/chronicle-test-1")
    event_response = client.post(
        f"/api/v1/sources/papers/{paper_id}/events",
        json={
            "event_type": "correction",
            "description": "A correction notice has been recorded for this discovered paper.",
            "source_url": "https://example.org/correction-notice",
            "verification_status": "human_verified",
        },
    )
    assert event_response.status_code == 201, event_response.text
    impact = event_response.json()["impact"]
    assert run_id in impact["affected_run_ids"]
    assert impact["report_versions_flagged_for_review"] == 1
    updated_report = client.get(f"/api/v1/evidence/runs/{run_id}/reports").json()[0]
    assert updated_report["review_required"] is True


def test_optional_synthesis_persists_source_linked_study_context(monkeypatch, client) -> None:
    from sqlalchemy import select

    from app.models.entities import Study
    from conftest import TestingSessionLocal

    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        research_pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            openai_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
            openai_api_base="https://model.example/v1",
            openai_model="test-model",
        ),
    )

    async def fake_search_papers(question: str, limit: int = 10, provider: str = "all") -> dict:
        return {
            "query": question,
            "providers_requested": provider,
            "provider_errors": {},
            "results": [{
                "provider": "crossref",
                "external_id": "10.5555/study-context-test",
                "doi": "10.5555/study-context-test",
                "title": "Evaluation Methods in Evidence Research",
                "authors": ["Example Researcher"],
                "abstract": "We conducted a randomized controlled study of 120 adult participants. The intervention used a provenance-aware workflow. Outcomes included answer accuracy and citation traceability. Limitations include one institution and a short follow-up period.",
                "publication_year": 2025,
                "publisher": "Example Publisher",
                "landing_url": "https://doi.org/10.5555/study-context-test",
            }],
        }

    async def fake_extract_claims_from_passages(question: str, passages: list[dict], api_key: str, api_base: str, model: str) -> list[dict]:
        return []

    async def fake_synthesize_evidence(question: str, passages: list[dict], api_key: str, api_base: str, model: str) -> dict:
        passage_id = passages[0]["id"]
        return {
            "executive_summary": "The retrieved abstract describes a randomized evaluation with a stated population, intervention, outcomes and limitations.",
            "findings": [],
            "study_characterizations": [{
                "passage_id": passage_id,
                "study_type": "Randomized controlled study",
                "population": "120 adult participants",
                "method": "Randomized controlled evaluation",
                "intervention": "Provenance-aware workflow",
                "outcomes": ["Answer accuracy", "Citation traceability"],
                "limitations": ["One institution", "Short follow-up period"],
            }],
            "disagreements": [],
            "limitations": ["Only the abstract was retrieved."],
            "candidate_research_questions": [],
            "uncertainty_statement": "The structured fields are model-inferred from an abstract and require full-text verification.",
            "input_passage_ids": [passage_id],
            "validated_source_references": True,
            "human_review_required": True,
        }

    monkeypatch.setattr(research_pipeline, "search_papers", fake_search_papers)
    monkeypatch.setattr(research_pipeline, "extract_claims_from_passages", fake_extract_claims_from_passages)
    monkeypatch.setattr(research_pipeline, "synthesize_evidence", fake_synthesize_evidence)

    created = client.post(
        "/api/v1/research/runs",
        json={
            "question": "What methods evaluate provenance-aware research workflows?",
            "mode": "academic",
            "max_sources": 3,
            "execute": False,
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    asyncio.run(research_pipeline.execute_research_run(run_id))

    with TestingSessionLocal() as db:
        study = db.scalar(select(Study).where(Study.extraction_basis == "model_inferred"))
        assert study is not None
        assert study.source_passage_id
        assert study.study_type == "Randomized controlled study"
        assert study.population == "120 adult participants"
        assert "Citation traceability" in study.outcomes
        study_id = study.id
        passage_id = study.source_passage_id

    reports = client.get(f"/api/v1/evidence/runs/{run_id}/reports").json()
    assert reports[0]["evidence_snapshot"]["study_ids"] == [study_id]
    assert "Extracted study context" in reports[0]["content_markdown"]
    assert "Randomized controlled study" in reports[0]["content_markdown"]

    graph = client.get(f"/api/v1/evidence/runs/{run_id}/graph").json()
    assert any(node["id"] == f"study:{study_id}" for node in graph["nodes"])
    assert any(edge["source"] == f"passage:{passage_id}" and edge["target"] == f"study:{study_id}" for edge in graph["edges"])

    passport = client.get(f"/api/v1/evidence/runs/{run_id}/passport?format=json").json()
    assert any(item["id"] == study_id and item["source_passage_id"] == passage_id for item in passport["studies"])
    assert any(item["target_entity_id"] == study_id and item["action"] == "study.context_extracted" for item in passport["audit_events"])
