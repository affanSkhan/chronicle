"""Deterministic, bounded research planning for Chronicle's four execution profiles.

The planner produces auditable query variants and module selections. It does not
claim to infer a novel research strategy or to replace expert scope decisions.
"""
from __future__ import annotations

import re
from typing import Any

_PROFILE_DATA: dict[str, dict[str, Any]] = {
    "quick": {
        "label": "Quick Discovery",
        "focus": "Find a fast orientation to the topic, major approaches, and accessible evidence. Keep the conclusion explicitly preliminary.",
        "queries": ["{question}", "{question} overview key findings applications"],
        "modules": [
            "Crossref/OpenAlex metadata retrieval",
            "DOI/title deduplication and abstract passage capture",
            "Compact initial evidence snapshot and coverage limitations",
        ],
        "stages": {"claim_extraction": False, "evidence_synthesis": False, "dependency_candidate_scan": False},
    },
    "deep": {
        "label": "Deep Research",
        "focus": "Broaden coverage across methods, results, limitations, and open research questions. Distinguish recurring evidence from isolated findings.",
        "queries": ["{question}", "{question} methods evaluation results", "{question} limitations open research questions"],
        "modules": [
            "Multi-query scholarly discovery",
            "DOI/title deduplication and abstract passage capture",
            "Optional source-linked claim extraction and synthesis",
            "Coverage, uncertainty, and limitation disclosure",
        ],
        "stages": {"claim_extraction": True, "evidence_synthesis": True, "dependency_candidate_scan": False},
        "stages": {"claim_extraction": True, "evidence_synthesis": True, "dependency_candidate_scan": False},
    },
    "academic": {
        "label": "Academic Review",
        "focus": "Compare study design, population, method, outcome definitions, results, and limitations. Treat studies as non-comparable when context does not justify a direct comparison.",
        "queries": ["{question}", "{question} study design methodology dataset", "{question} outcomes findings limitations comparison"],
        "modules": [
            "Multi-query scholarly discovery",
            "Source-linked study-context extraction (when a model is configured)",
            "Evidence-linked synthesis and disagreement notes (when a model is configured)",
            "Coverage, uncertainty, and limitation disclosure",
        ],
    },
    "forensic": {
        "label": "Forensic Analysis",
        "focus": "Search for conflicting findings, qualifications, source lineage, and post-publication updates. A source-status signal is a review prompt, not an automatic verdict.",
        "queries": ["{question}", "{question} conflicting findings contradictory evidence", "{question} correction retraction shared dataset source dependence"],
        "modules": [
            "Conflict-oriented scholarly query expansion",
            "Evidence-linked claims and qualification notes (when a model is configured)",
            "Existing source timeline and dependency graph for separate reviewer inspection",
            "Human review and audit trail for consequential changes",
        ],
        "stages": {"claim_extraction": True, "evidence_synthesis": True, "dependency_candidate_scan": True},
    },
}

def focus_for_mode(mode: str) -> str:
    """Return a concise, inspectable focus instruction for a research mode."""
    return _PROFILE_DATA.get(str(mode).lower(), _PROFILE_DATA["deep"])["focus"]


def build_research_plan(question: str, mode: str, max_sources: int) -> dict[str, Any]:
    """Build a deterministic execution plan that respects source and query budgets."""
    clean_question = re.sub(r"\s+", " ", question or "").strip()
    if not clean_question:
        raise ValueError("A research question is required.")
    budget = max(1, min(int(max_sources), 50))
    selected_mode = str(mode or "deep").lower()
    if selected_mode not in _PROFILE_DATA:
        selected_mode = "deep"
    profile = _PROFILE_DATA[selected_mode]
    queries = [template.format(question=clean_question) for template in profile["queries"]]
    # Do not run more planned searches than the source budget can meaningfully support.
    queries = queries[: min(len(queries), budget)]
    return {
        "version": "1.0",
        "mode": selected_mode,
        "profile_label": profile["label"],
        "focus": profile["focus"],
        "source_budget": budget,
        "query_budget": len(queries),
        "queries": queries,
        "modules": list(profile["modules"]),
        "stages": dict(profile["stages"]),
        "steps": [
            "Normalize the question and select the requested execution profile.",
            f"Run {len(queries)} bounded scholarly metadata search(es) against Crossref/OpenAlex.",
            "Deduplicate records and preserve the queries that surfaced each source.",
            "Persist available abstracts as passages and keep model outputs marked for review.",
            "Save a versioned report snapshot with search coverage and limitations.",
        ],
        "disclaimer": "The planner is deterministic and query-expansion based; it is not a learned autonomous planner. Source coverage remains limited to configured providers.",
    }
