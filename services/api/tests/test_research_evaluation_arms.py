import asyncio

from app.services import research_pipeline
from app.services.evaluation_arms import configure_evaluation_arm
from app.services.research_planner import build_research_plan


QUESTION = "How does evidence provenance improve research reliability?"


def _result(index: int) -> dict:
    return {
        "doi": f"10.5555/chronicle.test.{index}",
        "title": f"Evidence provenance test study {index}",
        "authors": ["Test Author"],
        "abstract": f"This is a synthetic test abstract for study {index}.",
        "landing_url": f"https://example.test/study-{index}",
        "publisher": "Test Publisher",
        "publication_year": 2025,
        "provider": "test",
        "external_id": f"test-{index}",
    }


def test_iterative_arm_performs_bounded_follow_up_searches(monkeypatch):
    calls: list[str] = []

    async def fake_search(query: str, limit: int, provider: str = "all") -> dict:
        calls.append(query)
        # Each search returns one new source so the evidence-gap loop has a reason
        # to continue until its explicit two-iteration ceiling.
        return {"results": [_result(len(calls))], "provider_errors": {}}

    monkeypatch.setattr(research_pipeline, "search_papers", fake_search)
    plan = configure_evaluation_arm(
        build_research_plan(QUESTION, "deep", max_sources=4), "B", question=QUESTION
    )

    response, executed_plan = asyncio.run(
        research_pipeline._execute_planned_search(QUESTION, "deep", 4, plan=plan)
    )

    assert len(calls) == 3
    assert len(response["results"]) == 3
    assert executed_plan["query_budget"] == 3
    assert len(executed_plan["research_iterations"]) == 2
    assert all(item["reason"] == "source_budget_gap_after_initial_retrieval" for item in executed_plan["research_iterations"])


def test_standard_rag_arm_never_runs_follow_up_searches(monkeypatch):
    calls: list[str] = []

    async def fake_search(query: str, limit: int, provider: str = "all") -> dict:
        calls.append(query)
        return {"results": [_result(len(calls))], "provider_errors": {}}

    monkeypatch.setattr(research_pipeline, "search_papers", fake_search)
    plan = configure_evaluation_arm(
        build_research_plan(QUESTION, "deep", max_sources=4), "A", question=QUESTION
    )

    response, executed_plan = asyncio.run(
        research_pipeline._execute_planned_search(QUESTION, "deep", 4, plan=plan)
    )

    assert calls == [QUESTION]
    assert len(response["results"]) == 1
    assert executed_plan["query_budget"] == 1
    assert executed_plan.get("research_iterations", []) == []
