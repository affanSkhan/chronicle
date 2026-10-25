"""Deterministic, bounded research planning for Chronicle's four execution profiles.

This module defines visible execution policy, not hidden model reasoning or a learned
autonomous planner. All external work remains subject to explicit query/source budgets.
"""
from __future__ import annotations

import re
from typing import Any


_PROFILE_DATA: dict[str, dict[str, Any]] = {
    "quick": {
        "label": "Quick Discovery",
        "focus": "Provide a fast, preliminary orientation to the topic and accessible evidence.",
        "queries": ["{question}", "{question} overview key findings applications"],
        "modules": [
            "Crossref/OpenAlex metadata retrieval",
            "DOI/title deduplication and abstract passage capture",
            "Compact initial evidence snapshot and coverage limitations",
        ],
        "stages": {
            "claim_extraction": False,
            "evidence_synthesis": False,
            "dependency_candidate_scan": False,
        },
    },
    "deep": {
        "label": "Deep Research",
        "focus": "Broaden coverage across methods, results, limitations, and open questions; distinguish recurring evidence from isolated findings.",
        "queries": ["{question}", "{question} methods evaluation results", "{question} limitations open research questions"],
        "modules": [
            "Multi-query scholarly discovery",
            "DOI/title deduplication and abstract passage capture",
            "Optional source-linked claim extraction and synthesis",
            "Coverage, uncertainty, and limitation disclosure",
        ],
        "stages": {
            "claim_extraction": True,
            "evidence_synthesis": True,
            "dependency_candidate_scan": False,
        },
    },
    "academic": {
        "label": "Academic Review",
        "focus": "Compare study design, population, method, outcome definitions, results, and limitations; mark studies non-comparable when context does not justify direct comparison.",
        "queries": ["{question}", "{question} study design methodology dataset", "{question} outcomes findings limitations comparison"],
        "modules": [
            "Multi-query scholarly discovery",
            "Source-linked study-context extraction (when a model is configured)",
            "Evidence-linked synthesis and disagreement notes (when a model is configured)",
            "Coverage, uncertainty, and limitation disclosure",
        ],
        "stages": {
            "claim_extraction": True,
            "evidence_synthesis": True,
            "dependency_candidate_scan": False,
        },
    },
    "forensic": {
        "label": "Forensic Analysis",
        "focus": "Search for conflicting findings, qualifications, source lineage, and post-publication updates. Signals trigger review; they are not automatic verdicts.",
        "queries": ["{question}", "{question} conflicting findings contradictory evidence", "{question} correction retraction shared dataset source dependence"],
        "modules": [
            "Conflict-oriented scholarly query expansion",
            "Evidence-linked claims and qualification notes (when a model is configured)",
            "Run-scoped shared-dataset and overlap candidate scan",
            "Source timeline, dependency graph, and audit trail for reviewer inspection",
        ],
        "stages": {
            "claim_extraction": True,
            "evidence_synthesis": True,
            "dependency_candidate_scan": True,
        },
    },
}


def focus_for_mode(mode: str) -> str:
    """Return a concise, inspectable focus instruction for a research mode."""
    return _PROFILE_DATA.get(str(mode).lower(), _PROFILE_DATA["deep"])["focus"]


def build_research_plan(question: str, mode: str, max_sources: int) -> dict[str, Any]:
    """Build a deterministic execution plan that respects source and query budgets."""
    clean_question = re.sub(r"\\s+", " ", question or "").strip()
    if not clean_question:
        raise ValueError("A research question is required.")
    budget = max(1, min(int(max_sources), 50))
    selected_mode = str(mode or "deep").lower()
    if selected_mode not in _PROFILE_DATA:
        selected_mode = "deep"

    profile = _PROFILE_DATA[selected_mode]
    queries = [template.format(question=clean_question) for template in profile["queries"]]
    queries = queries[: min(len(queries), budget)]
    stages = dict(profile["stages"])
    steps = [
        "Normalize the question and select the requested execution profile.",
        f"Run {len(queries)} bounded scholarly metadata search(es) against Crossref/OpenAlex.",
        "Deduplicate records and preserve the query trail for each source.",
        "Persist available abstracts as passages with source identifiers.",
    ]
    if stages["claim_extraction"]:
        steps.append("Run optional structured claim extraction when a server-side model is configured.")
    if stages["evidence_synthesis"]:
        steps.append("Run optional evidence-bounded synthesis when a server-side model is configured.")
    if stages["dependency_candidate_scan"]:
        steps.append("Scan only this run's saved sources for possible shared-dataset or overlap links; do not auto-persist suggestions.")
    steps.append("Save a versioned report snapshot with coverage, uncertainty, and review limitations.")

    return {
        "version": "1.1",
        "mode": selected_mode,
        "profile_label": profile["label"],
        "focus": profile["focus"],
        "source_budget": budget,
        "query_budget": len(queries),
        "queries": queries,
        "modules": list(profile["modules"]),
        "stages": stages,
        "steps": steps,
        "disclaimer": (
            "The planner is deterministic and query-expansion based, not a learned autonomous planner. "
            "External coverage remains limited to configured providers; source-dependence scores are heuristic."
        ),
    }
