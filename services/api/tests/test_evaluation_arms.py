import pytest

from app.services.evaluation_arms import ARM_DEFINITIONS, configure_evaluation_arm
from app.services.research_planner import build_research_plan


QUESTION = "How do evidence provenance systems improve research reliability?"


def test_arms_match_ff180_feature_matrix():
    plan = build_research_plan(QUESTION, "deep", 10)
    configured = {arm: configure_evaluation_arm(plan, arm, question=QUESTION) for arm in "ABCD"}

    assert configured["A"]["queries"] == [QUESTION]
    assert configured["A"]["evaluation"]["feature_flags"]["research_planning"] is False
    assert configured["A"]["stages"]["claim_extraction"] is False
    assert configured["A"]["stages"]["evidence_synthesis"] is True

    assert configured["B"]["evaluation"]["feature_flags"]["iterative_retrieval"] is True
    assert configured["B"]["evaluation"]["feature_flags"]["claim_graph"] is False
    assert configured["B"]["stages"]["claim_extraction"] is False

    assert configured["C"]["evaluation"]["feature_flags"]["claim_graph"] is True
    assert configured["C"]["evaluation"]["feature_flags"]["temporal_propagation"] is False
    assert configured["C"]["stages"]["dependency_candidate_scan"] is True

    assert configured["D"]["evaluation"]["feature_flags"]["temporal_propagation"] is True
    assert configured["D"]["stages"]["claim_extraction"] is True


def test_missing_arm_defaults_to_full_lifecycle_without_mutating_input():
    plan = build_research_plan(QUESTION, "deep", 5)
    before = {key: value for key, value in plan.items()}
    configured = configure_evaluation_arm(plan, None, question=QUESTION)

    assert configured["evaluation_arm"] == "D"
    assert plan == before
    assert "evaluation" not in plan


def test_unknown_arm_is_rejected():
    with pytest.raises(ValueError, match="A, B, C, or D"):
        configure_evaluation_arm(build_research_plan(QUESTION, "deep", 5), "E", question=QUESTION)


def test_arms_have_explicit_complete_feature_definitions():
    expected = {
        "research_planning", "iterative_retrieval", "claim_graph", "dependency_graph",
        "temporal_propagation", "report_versioning", "audit_trail",
    }
    for definition in ARM_DEFINITIONS.values():
        assert expected.issubset(definition)
