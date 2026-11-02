import asyncio
import json

from app.services import research_orchestrator


def test_planner_graph_falls_back_without_model_and_preserves_budgets(monkeypatch):
    monkeypatch.setattr(research_orchestrator, "get_llm_config", lambda settings: ("", "", ""))
    plan = asyncio.run(research_orchestrator.build_agentic_research_plan(
        "How does retrieval practice affect long-term learning?", "forensic", 3
    ))
    assert plan["planner"]["backend"] == "deterministic_fallback"
    assert plan["planner"]["nodes"] == ["query_planner_agent", "query_budget_critic", "specialist_role_contracts"]
    assert [role["role"] for role in plan["specialist_roles"]] == ["discovery", "study_appraisal", "claim_synthesis", "temporal_monitor"]
    assert plan["queries"][0] == "How does retrieval practice affect long-term learning?"
    assert len(plan["queries"]) <= 3


def test_planner_graph_accepts_bounded_suggestions_and_rejects_urls(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "queries": [
                    "retrieval practice long-term learning randomized studies",
                    "retrieval practice long-term retention limitations",
                    "https://example.com/invalid",
                    "retrieval practice long-term learning randomized studies",
                ]
            })}}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        research_orchestrator, "get_llm_config",
        lambda settings: ("test-token", "https://provider.example/v1", "test-model"),
    )
    monkeypatch.setattr(research_orchestrator.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    plan = asyncio.run(research_orchestrator.build_agentic_research_plan(
        "How does retrieval practice affect long-term learning?", "forensic", 3
    ))
    assert plan["planner"]["backend"] == "langgraph_llm_planner"
    assert plan["queries"][0] == "How does retrieval practice affect long-term learning?"
    assert len(plan["queries"]) <= 3
    assert all("://" not in query for query in plan["queries"])
    assert len({query.casefold() for query in plan["queries"]}) == len(plan["queries"])
    assert all(role["human_review_required"] for role in plan["specialist_roles"])


def test_query_critic_preserves_long_original_question():
    long_question = "How does retrieval practice affect long-term learning outcomes? " + (
        "with careful replication across populations " * 12
    )
    state = {
        "question": long_question,
        "mode": "deep",
        "max_sources": 3,
        "base_plan": research_orchestrator.build_research_plan(long_question, "deep", 3),
        "proposed_queries": ["retrieval practice study outcomes"],
        "planner_backend": "langgraph_llm_planner",
        "fallback_reason": "",
    }
    result = research_orchestrator._query_critic(state)
    assert result["final_plan"]["queries"][0] == long_question.strip()
    assert len(result["final_plan"]["queries"]) <= 3


def test_specialist_role_contracts_record_bounded_reviewable_stage_outputs():
    plan = asyncio.run(research_orchestrator.build_agentic_research_plan(
        "How does retrieval practice affect long-term learning?", "forensic", 3
    ))
    outputs = research_orchestrator.execute_specialist_role_contracts(
        plan, source_count=3, passage_count=8, claim_count=2, impacted_entity_count=1
    )
    assert [item["role"] for item in outputs] == ["discovery", "study_appraisal", "claim_synthesis", "temporal_monitor"]
    assert [item["candidate_count"] for item in outputs] == [3, 8, 2, 1]
    assert all(item["human_review_required"] for item in outputs)


def test_specialist_role_outputs_mark_profile_disabled_stages_as_skipped():
    plan = asyncio.run(research_orchestrator.build_agentic_research_plan(
        "What is evidence provenance?", "quick", 2
    ))
    outputs = research_orchestrator.execute_specialist_role_contracts(
        plan, source_count=2, passage_count=2, claim_count=3, impacted_entity_count=4
    )
    by_role = {item["role"]: item for item in outputs}
    assert by_role["discovery"]["status"] == "completed"
    assert by_role["claim_synthesis"]["status"] == "skipped_by_profile"
    assert by_role["temporal_monitor"]["status"] == "skipped_by_profile"
    assert by_role["claim_synthesis"]["candidate_count"] == 0
