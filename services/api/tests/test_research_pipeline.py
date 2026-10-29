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
    assert run["status"] == "completed_with_limitations"
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
        passage_id = passages[0]["id"]
        return [{
            "statement": "The intervention is evaluated using a provenance-aware workflow.",
            "scope": {"population": "120 adult participants"},
            "uncertainty_notes": "Extracted from one abstract; inspect the full text.",
            "evidence": [{
                "passage_id": passage_id,
                "relation_type": "supports",
                "rationale": "The abstract describes the intervention and evaluation.",
            }],
        }]

    async def fake_synthesize_evidence(question: str, passages: list[dict], api_key: str, api_base: str, model: str) -> dict:
        passage_id = passages[0]["id"]
        return {
            "executive_summary": "The retrieved abstract describes a randomized evaluation with a stated population, intervention, outcomes and limitations.",
            "findings": [{
                "statement": "The abstract reports a provenance-aware intervention in one institution.",
                "evidence_passage_ids": [passage_id],
                "relation_type": "qualifies",
                "context_note": "The study is limited to one institution.",
            }],
            "research_opportunities": [{
                "question": "Does this result generalize across institutions?",
                "rationale": "The abstract reports only one institution, which leaves transferability unresolved.",
                "evidence_passage_ids": [passage_id],
                "prior_art_search_queries": ["external validation across institutions provenance-aware workflow"],
                "alternative_explanations": ["The observed result may depend on a local workflow."],
                "falsification_plan": "Pre-register an external multi-institution validation and test whether the effect persists.",
                "review_status": "requires_prior_art_review",
            }],
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
    report_version_node = next(node for node in graph["nodes"] if node["type"] == "report_version")
    conclusion_node = next(node for node in graph["nodes"] if node["type"] == "conclusion")
    recommendation_node = next(node for node in graph["nodes"] if node["type"] == "recommendation")
    assert conclusion_node["review_required"] is True
    assert recommendation_node["prior_art_search_queries"] == ["external validation across institutions provenance-aware workflow"]
    assert any(edge["source"] == f"passage:{passage_id}" and edge["target"] == conclusion_node["id"] and edge["type"] == "qualifies" for edge in graph["edges"])
    assert any(edge["source"] == f"passage:{passage_id}" and edge["target"] == recommendation_node["id"] for edge in graph["edges"])
    assert report_version_node["report_version_number"] == reports[0]["version_number"]
    assert conclusion_node["evidence_passage_ids"] == [passage_id]
    assert conclusion_node["claim_ids"]
    assert recommendation_node["evidence_passage_ids"] == [passage_id]
    assert any(
        edge["source"] == f"claim:{conclusion_node['claim_ids'][0]}"
        and edge["target"] == conclusion_node["id"]
        and edge["type"] == "contributes_to_conclusion"
        for edge in graph["edges"]
    )
    assert any(edge["source"] == report_version_node["id"] and edge["target"] == recommendation_node["id"] and edge["type"] == "proposes_recommendation" for edge in graph["edges"])

    passport = client.get(f"/api/v1/evidence/runs/{run_id}/passport?format=json").json()
    assert any(item["id"] == study_id and item["source_passage_id"] == passage_id for item in passport["studies"])
    assert any(item["target_entity_id"] == study_id and item["action"] == "study.context_extracted" for item in passport["audit_events"])


def test_failed_research_run_preserves_execution_plan(monkeypatch, client) -> None:
    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        research_pipeline,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None, openai_api_base="https://api.openai.com/v1", openai_model=""),
    )

    async def failing_search(question: str, limit: int = 10, provider: str = "all") -> dict:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(research_pipeline, "search_papers", failing_search)
    created = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How should Chronicle expose failed planner runs?",
            "mode": "forensic",
            "max_sources": 4,
            "execute": False,
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    asyncio.run(research_pipeline.execute_research_run(run_id))

    from app.models.entities import ResearchRun
    with TestingSessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.configuration["planner_version"] == "1.1"
        plan = run.configuration["execution_plan"]
        assert plan["mode"] == "forensic"
        assert "conflicting findings contradictory evidence" in " ".join(plan["queries"])
        assert run.configuration["planned_search_queries"] == plan["queries"]


def test_quick_discovery_skips_configured_model_calls(monkeypatch, client) -> None:
    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        research_pipeline, "get_settings",
        lambda: SimpleNamespace(openai_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
            openai_api_base="https://model.example/v1", openai_model="test-model"),
    )

    async def fake_search_papers(question: str, limit: int = 10, provider: str = "all") -> dict:
        return {"query": question, "providers_requested": provider, "provider_errors": {}, "results": [{
            "provider": "crossref", "external_id": "10.5555/quick-mode-test", "doi": "10.5555/quick-mode-test",
            "title": "Quick mode test source", "authors": ["Test Author"],
            "abstract": "This abstract describes a measurable outcome in the target research topic.",
            "publication_year": 2025, "publisher": "Test Publisher",
            "landing_url": "https://doi.org/10.5555/quick-mode-test",
        }]}

    async def unexpected_model_call(**kwargs):
        raise AssertionError("Quick Discovery must not call LLM stages.")

    monkeypatch.setattr(research_pipeline, "search_papers", fake_search_papers)
    monkeypatch.setattr(research_pipeline, "extract_claims_from_passages", unexpected_model_call)
    monkeypatch.setattr(research_pipeline, "synthesize_evidence", unexpected_model_call)
    created = client.post("/api/v1/research/runs", json={
        "question": "Give a quick overview of evidence provenance in research.",
        "mode": "quick", "max_sources": 4, "execute": False,
    })
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    asyncio.run(research_pipeline.execute_research_run(run_id))

    report = client.get(f"/api/v1/evidence/runs/{run_id}/reports").json()[0]
    assert report["evidence_snapshot"]["execution_plan"]["stages"]["claim_extraction"] is False
    assert report["evidence_snapshot"]["model_synthesis_completed"] is False
    assert "Quick Discovery profile" in report["content_markdown"]


def test_forensic_mode_returns_run_scoped_dependency_suggestions(monkeypatch, client) -> None:
    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        research_pipeline, "get_settings",
        lambda: SimpleNamespace(openai_api_key=None, openai_api_base="https://api.openai.com/v1", openai_model=""),
    )

    async def fake_search_papers(question: str, limit: int = 10, provider: str = "all") -> dict:
        return {"query": question, "providers_requested": provider, "provider_errors": {}, "results": [
            {"provider": "crossref", "external_id": "10.5555/forensic-a", "doi": "10.5555/forensic-a",
             "title": "Forensic study A", "authors": ["Author A"],
             "abstract": "This study evaluated clinical outcomes using MIMIC-IV patient records with a model.",
             "publication_year": 2024, "publisher": "Test Publisher", "landing_url": "https://doi.org/10.5555/forensic-a"},
            {"provider": "crossref", "external_id": "10.5555/forensic-b", "doi": "10.5555/forensic-b",
             "title": "Forensic study B", "authors": ["Author B"],
             "abstract": "This study analysed MIMIC-IV records for a different outcome and model.",
             "publication_year": 2025, "publisher": "Test Publisher", "landing_url": "https://doi.org/10.5555/forensic-b"},
        ]}

    monkeypatch.setattr(research_pipeline, "search_papers", fake_search_papers)
    created = client.post("/api/v1/research/runs", json={
        "question": "Investigate conflicting findings and source dependence in research.",
        "mode": "forensic", "max_sources": 5, "execute": False,
    })
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    asyncio.run(research_pipeline.execute_research_run(run_id))

    response = client.get(f"/api/v1/evidence/runs/{run_id}/reports")
    assert response.status_code == 200, response.text
    report = response.json()[0]
    snapshot = report["evidence_snapshot"]
    assert snapshot["execution_plan"]["stages"]["dependency_candidate_scan"] is True
    assert snapshot["dependency_candidates"]
    assert snapshot["dependency_candidates"][0]["relation_type"] == "same_dataset"
    analysis = snapshot["source_dependence_analysis"]
    assert analysis["status"] == "heuristic_scan_completed"
    assert analysis["raw_source_count"] == 2
    assert analysis["candidate_link_count"] >= 1
    assert analysis["candidate_cluster_count"] == 1
    assert analysis["clusters"][0]["source_count"] == 2
    assert "not proven independent" in analysis["interpretation"]
    assert "Potential source-dependence analysis" in report["content_markdown"]

    with TestingSessionLocal() as db:
        from app.models.entities import PaperDependency
        assert db.query(PaperDependency).count() == 0


def test_run_is_completed_with_limitations_when_some_provider_queries_fail(monkeypatch, client) -> None:
    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        research_pipeline,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None, openai_api_base="https://api.openai.com/v1", openai_model=""),
    )
    async def fake_search(question: str, limit: int = 10, provider: str = "all") -> dict:
        if "methods evaluation results" in question:
            return {
                "query": question, "providers_requested": provider,
                "provider_errors": {"crossref": "timeout"}, "results": [{
                    "provider": "openalex", "external_id": "W-limitation",
                    "doi": None, "title": "A partial result", "authors": [],
                    "abstract": "An abstract with limited evidence.", "publication_year": 2024,
                    "publisher": "Example", "landing_url": "https://example.org/paper",
                }],
            }
        return {
            "query": question, "providers_requested": provider,
            "provider_errors": {}, "results": [{
                "provider": "openalex", "external_id": "W-limitation",
                "doi": None, "title": "A partial result", "authors": [],
                "abstract": "An abstract with limited evidence.", "publication_year": 2024,
                "publisher": "Example", "landing_url": "https://example.org/paper",
            }],
        }
    monkeypatch.setattr(research_pipeline, "search_papers", fake_search)
    created = client.post("/api/v1/research/runs", json={
        "question": "What should a partial research result report?",
        "mode": "deep", "max_sources": 5, "execute": False,
    })
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    asyncio.run(research_pipeline.execute_research_run(run_id))
    run = client.get(f"/api/v1/research/runs/{run_id}").json()
    assert run["status"] == "completed_with_limitations"
    report = client.get(f"/api/v1/evidence/runs/{run_id}/reports").json()[0]
    assert report["evidence_snapshot"]["completion_status"] == "completed_with_limitations"
    assert report["evidence_snapshot"]["completed_with_limitations"] is True
    assert "provider_errors" in report["evidence_snapshot"]
