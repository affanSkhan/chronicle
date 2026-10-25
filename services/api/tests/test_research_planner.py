from app.services.research_planner import build_research_plan, focus_for_mode


def test_modes_produce_distinct_bounded_execution_plans():
    question = "How does evidence provenance improve research reliability?"
    plans = {
        mode: build_research_plan(question, mode, max_sources=5)
        for mode in ("quick", "deep", "academic", "forensic")
    }

    assert len({tuple(p["queries"]) for p in plans.values()}) == 4
    assert len({p["focus"] for p in plans.values()}) == 4
    assert len({tuple(p["modules"]) for p in plans.values()}) == 4
    for plan in plans.values():
        assert plan["queries"][0] == question
        assert 1 <= plan["query_budget"] <= 5
        assert plan["source_budget"] == 5
        assert plan["version"] == "1.1"
        assert plan["steps"]


def test_planner_respects_small_source_budget_and_normalizes_whitespace():
    plan = build_research_plan("  Compare  study methods  ", "academic", max_sources=1)
    assert plan["queries"] == ["Compare study methods"]
    assert plan["query_budget"] == 1


def test_unknown_mode_falls_back_to_deep_profile():
    plan = build_research_plan("How are papers compared?", "unknown", 3)
    assert plan["mode"] == "deep"
    assert focus_for_mode("unknown") == focus_for_mode("deep")


def test_mode_stage_policies_are_materially_different():
    question = "How does evidence provenance improve research reliability?"
    quick = build_research_plan(question, "quick", 5)
    deep = build_research_plan(question, "deep", 5)
    academic = build_research_plan(question, "academic", 5)
    forensic = build_research_plan(question, "forensic", 5)

    assert quick["stages"] == {
        "claim_extraction": False,
        "evidence_synthesis": False,
        "dependency_candidate_scan": False,
    }
    assert deep["stages"]["claim_extraction"] is True
    assert deep["stages"]["evidence_synthesis"] is True
    assert deep["stages"]["dependency_candidate_scan"] is False
    assert academic["stages"]["claim_extraction"] is True
    assert academic["stages"]["evidence_synthesis"] is True
    assert forensic["stages"]["dependency_candidate_scan"] is True
