import asyncio
import json

from app.services import research_orchestrator


def test_planner_graph_falls_back_without_model_and_preserves_budgets(monkeypatch):
    monkeypatch.setattr(research_orchestrator, "get_llm_config", lambda settings: ("", "", ""))
    plan = asyncio.run(research_orchestrator.build_agentic_research_plan(
        "How does retrieval practice affect long-term learning?", "deep", 3
    ))
    assert plan["planner"]["backend"] == "deterministic_fallback"
    assert plan["planner"]["nodes"] == ["query_planner_agent", "query_budget_critic"]
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
        "How does retrieval practice affect long-term learning?", "deep", 3
    ))
    assert plan["planner"]["backend"] == "langgraph_llm_planner"
    assert plan["queries"][0] == "How does retrieval practice affect long-term learning?"
    assert len(plan["queries"]) <= 3
    assert all("://" not in query for query in plan["queries"])
    assert len({query.casefold() for query in plan["queries"]}) == len(plan["queries"])
