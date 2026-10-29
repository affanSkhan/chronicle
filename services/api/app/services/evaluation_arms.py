"""Deterministic feature matrix for the approved FF180 A-D experiment.

The arms vary functionality, never budgets or provider/model configuration. The
same label split and model settings must be reused when comparing predictions.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

ARM_IDS = ("A", "B", "C", "D")

ARM_DEFINITIONS: dict[str, dict[str, Any]] = {
    "A": {
        "name": "Standard RAG",
        "research_planning": False,
        "iterative_retrieval": False,
        "claim_graph": False,
        "dependency_graph": False,
        "temporal_propagation": False,
        "report_versioning": True,
        "audit_trail": True,
        "claim_extraction": False,
        "evidence_synthesis": True,
        "dependency_candidate_scan": False,
    },
    "B": {
        "name": "Iterative research agent",
        "research_planning": True,
        "iterative_retrieval": True,
        "claim_graph": False,
        "dependency_graph": False,
        "temporal_propagation": False,
        "report_versioning": True,
        "audit_trail": True,
        "claim_extraction": False,
        "evidence_synthesis": True,
        "dependency_candidate_scan": False,
    },
    "C": {
        "name": "Claim and provenance graph",
        "research_planning": True,
        "iterative_retrieval": True,
        "claim_graph": True,
        "dependency_graph": True,
        "temporal_propagation": False,
        "report_versioning": True,
        "audit_trail": True,
        "claim_extraction": True,
        "evidence_synthesis": True,
        "dependency_candidate_scan": True,
    },
    "D": {
        "name": "Full lifecycle prototype",
        "research_planning": True,
        "iterative_retrieval": True,
        "claim_graph": True,
        "dependency_graph": True,
        "temporal_propagation": True,
        "report_versioning": True,
        "audit_trail": True,
        "claim_extraction": True,
        "evidence_synthesis": True,
        "dependency_candidate_scan": True,
    },
}


def configure_evaluation_arm(
    plan: dict[str, Any],
    arm: str | None,
    *,
    question: str,
) -> dict[str, Any]:
    """Apply an approved, reproducible A-D feature policy to an execution plan.

    Missing arm selects D (normal full-lifecycle product behaviour). A is a
    single-query baseline and intentionally bypasses model-driven query planning.
    """
    selected = str(arm or "D").strip().upper()
    if selected not in ARM_IDS:
        raise ValueError("evaluation_arm must be one of A, B, C, or D.")

    configured = deepcopy(plan)
    definition = ARM_DEFINITIONS[selected]
    if selected == "A":
        configured["queries"] = [question.strip()]
        configured["query_budget"] = 1
        configured["planner"] = {
            "framework": "disabled for baseline A",
            "nodes": [],
            "backend": "single_pass_rag",
            "fallback_reason": None,
            "query_limit_enforced": 1,
            "note": "Arm A executes the original question once without agent-led query planning.",
        }

    configured["stages"] = {
        "claim_extraction": definition["claim_extraction"],
        "evidence_synthesis": definition["evidence_synthesis"],
        "dependency_candidate_scan": definition["dependency_candidate_scan"],
    }
    configured["evaluation"] = {
        "protocol": "VIIT FF180 A-D comparison",
        "arm": selected,
        "name": definition["name"],
        "feature_flags": {
            key: bool(definition[key])
            for key in (
                "research_planning", "iterative_retrieval", "claim_graph",
                "dependency_graph", "temporal_propagation",
                "report_versioning", "audit_trail",
            )
        },
        "model_and_budgets_are_external_controls": True,
    }
    configured["evaluation_arm"] = selected
    configured["features"] = dict(configured["evaluation"]["feature_flags"])
    configured["features"]["max_additional_search_iterations"] = 2 if definition["iterative_retrieval"] else 0
    configured["version"] = str(configured.get("version", "1.1"))
    return configured
