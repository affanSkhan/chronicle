from app.services.research_planner import build_research_plan, merge_task_results


def test_four_modes_produce_distinct_bounded_execution_plans() -> None:
    question = "How does evidence provenance improve research reliability?"
    plans = {
        mode: build_research_plan(question, mode, 10)
        for mode in ("quick", "deep", "academic", "forensic")
    }

    assert len(plans["quick"]["subtasks"]) == 1
    assert len(plans["deep"]["subtasks"]) == 3
    assert len(plans["academic"]["subtasks"]) == 3
    assert len(plans["forensic"]["subtasks"]) == 4
    assert len({tuple(plan["enabled_modules"]) for plan in plans.values()}) == 4
    assert plans["quick"]["features"]["llm_synthesis"] is False
    assert plans["academic"]["features"]["llm_synthesis"] is True
    assert "dependency_family_summary" in plans["forensic"]["enabled_modules"]

    for mode, plan in plans.items():
        assert plan["budgets"]["max_subqueries"] == len(plan["subtasks"])
        assert plan["budgets"]["max_retrieved_sources"] == 10
        assert plan["budgets"]["per_subquery_result_limit"] <= 10
        assert plan["budgets"]["deadline_seconds"] > 0
        assert all(task["query"].startswith(question) for task in plan["subtasks"])
        assert all(task["status"] == "planned" for task in plan["subtasks"])


def test_merge_task_results_round_robins_and_deduplicates() -> None:
    primary = [
        {"doi": "10.1234/a", "title": "Paper A", "abstract": "short"},
        {"doi": "10.1234/b", "title": "Paper B", "abstract": "b"},
    ]
    expanded = [
        {"doi": "10.1234/c", "title": "Paper C", "abstract": "c"},
        {"doi": "https://doi.org/10.1234/a", "title": "Paper A copy", "abstract": "a longer abstract", "authors": ["Author"]},
    ]

    merged = merge_task_results([("primary_discovery", primary), ("methods", expanded)], max_sources=3)

    assert [item["title"] for item in merged] == ["Paper A", "Paper C", "Paper B"]
    assert merged[0]["_retrieval_tasks"] == ["primary_discovery", "methods"]
    assert merged[0]["abstract"] == "a longer abstract"
    assert merged[0]["authors"] == ["Author"]
    assert len(merged) == 3


def test_plan_endpoint_returns_persisted_mode_plan(client) -> None:
    created = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How do publication changes affect research conclusions?",
            "mode": "forensic",
            "max_sources": 7,
            "execute": False,
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    response = client.get(f"/api/v1/research/runs/{run_id}/plan")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["run_id"] == run_id
    assert payload["mode"] == "forensic"
    assert payload["plan"]["profile_name"] == "Forensic Analysis"
    assert len(payload["plan"]["subtasks"]) == 4
    assert payload["plan"]["budgets"]["max_retrieved_sources"] == 7
