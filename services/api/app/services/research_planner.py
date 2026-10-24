"""Bounded, mode-specific research plans for Chronicle.

The planner records actionable steps and budgets, not hidden model reasoning.
Search expansions are deterministic so a run can be reproduced and tested.
"""
from __future__ import annotations

from math import ceil
import re
from typing import Any


_MODE_SPEC: dict[str, dict[str, Any]] = {
    "quick": {
        "label": "Quick Discovery",
        "deadline_seconds": 90,
        "max_agent_iterations": 1,
        "modules": [
            "scholarly_metadata_search",
            "identifier_and_title_deduplication",
            "abstract_passage_persistence",
            "coverage_disclosure",
            "candidate_dependency_detection",
            "dependency_family_summary",
            "compact_discovery_report",
        ],
        "llm_claim_extraction": False,
        "llm_synthesis": False,
        "subtasks": [
            ("primary_discovery", "Retrieve an initial set of relevant scholarly works", ""),
        ],
    },
    "deep": {
        "label": "Deep Research",
        "deadline_seconds": 300,
        "max_agent_iterations": 3,
        "modules": [
            "scholarly_metadata_search",
            "identifier_and_title_deduplication",
            "abstract_passage_persistence",
            "candidate_claim_extraction",
            "evidence_bounded_synthesis",
            "study_context_extraction",
            "counter_evidence_search",
            "candidate_dependency_detection",
            "dependency_family_summary",
            "coverage_disclosure",
            "versioned_report",
        ],
        "llm_claim_extraction": True,
        "llm_synthesis": True,
        "subtasks": [
            ("primary_discovery", "Retrieve the main literature set", ""),
            ("methods_and_results", "Broaden retrieval towards study methods and reported results", " study methods results evaluation"),
            ("limitations_and_gaps", "Look for limitations, conflicting findings and follow-up work", " limitations conflicting findings refuting evidence alternative explanations research gaps future work"),
        ],
    },
    "academic": {
        "label": "Academic Review",
        "deadline_seconds": 300,
        "max_agent_iterations": 3,
        "modules": [
            "scholarly_metadata_search",
            "identifier_and_title_deduplication",
            "abstract_passage_persistence",
            "candidate_claim_extraction",
            "evidence_bounded_synthesis",
            "study_context_extraction",
            "study_context_comparison",
            "candidate_dependency_detection",
            "dependency_family_summary",
            "coverage_disclosure",
            "versioned_report",
        ],
        "llm_claim_extraction": True,
        "llm_synthesis": True,
        "subtasks": [
            ("primary_discovery", "Retrieve papers directly relevant to the research question", ""),
            ("study_design", "Search for study designs, populations, datasets and methodologies", " study design methodology population dataset"),
            ("outcomes_and_limits", "Search for outcomes, limitations and comparable evaluation measures", " outcomes evaluation measures limitations"),
        ],
    },
    "forensic": {
        "label": "Forensic Analysis",
        "deadline_seconds": 300,
        "max_agent_iterations": 4,
        "modules": [
            "scholarly_metadata_search",
            "identifier_and_title_deduplication",
            "abstract_passage_persistence",
            "candidate_claim_extraction",
            "evidence_bounded_synthesis",
            "counter_evidence_search",
            "candidate_dependency_detection",
            "dependency_family_summary",
            "publication_update_search",
            "coverage_disclosure",
            "versioned_report",
        ],
        "llm_claim_extraction": True,
        "llm_synthesis": True,
        "subtasks": [
            ("primary_discovery", "Retrieve papers relevant to the question under investigation", ""),
            ("conflicting_evidence", "Actively search for conflicting findings and alternative explanations", " conflicting findings contradictory evidence alternative explanation"),
            ("independent_replication", "Search for replications and independently conducted studies", " replication independent study reproducibility"),
            ("publication_updates", "Search scholarly records for candidate correction, retraction and version-update notices", " correction retraction expression of concern updated version"),
        ],
    },
}


def _mode_value(mode: Any) -> str:
    value = getattr(mode, "value", mode)
    normalized = str(value or "deep").strip().lower()
    return normalized if normalized in _MODE_SPEC else "deep"


def build_research_plan(question: str, mode: Any, max_sources: int) -> dict[str, Any]:
    """Build an inspectable execution plan with hard query/source budgets."""
    normalized_question = re.sub(r"\s+", " ", question).strip()
    mode_value = _mode_value(mode)
    spec = _MODE_SPEC[mode_value]
    source_cap = max(1, min(int(max_sources), 50))
    task_specs = spec["subtasks"]
    task_count = len(task_specs)
    per_query = min(source_cap, max(1, ceil(source_cap / task_count) + 2))

    subtasks = []
    for task_id, purpose, suffix in task_specs:
        query = (normalized_question + suffix).strip()[:2200]
        subtasks.append({
            "id": task_id,
            "purpose": purpose,
            "query": query,
            "status": "planned",
            "result_count": 0,
            "provider_errors": {},
        })

    return {
        "planner_version": "1.0",
        "profile_id": mode_value,
        "profile_name": spec["label"],
        "original_question": normalized_question,
        "enabled_modules": list(spec["modules"]),
        "features": {
            "llm_claim_extraction": spec["llm_claim_extraction"],
            "llm_synthesis": spec["llm_synthesis"],
            "human_review_required": True,
            "source_status_checks_are_signals_not_authoritative_proof": True,
        },
        "budgets": {
            "max_subqueries": task_count,
            "max_retrieved_sources": source_cap,
            "per_subquery_result_limit": per_query,
            "max_workflow_steps": spec["max_agent_iterations"],
            "deadline_seconds": spec["deadline_seconds"],
        },
        "subtasks": subtasks,
        "status": "planned",
        "planning_note": (
            "This is a deterministic bounded-query planner, not a complete independent multi-agent orchestration or a private reasoning trace. "
            "Retrieved records are bibliographic metadata/abstracts; model-generated interpretations remain unverified. "
            "Publication-update queries surface candidate literature only; live Crossref/OpenAlex status checks are separate and not authoritative."
        ),
    }


def merge_task_results(
    task_results: list[tuple[str, list[dict[str, Any]]]],
    max_sources: int,
) -> list[dict[str, Any]]:
    """Round-robin task results, deduplicating by DOI then normalized title.

    Round-robin selection gives secondary queries a chance to contribute instead
    of letting the main query consume the whole source budget.
    """
    cap = max(1, min(int(max_sources), 50))
    if not task_results:
        return []

    def key_for(item: dict[str, Any]) -> str:
        doi = str(item.get("doi") or "").strip().lower()
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
        doi = re.sub(r"^doi:\s*", "", doi).rstrip(".")
        if doi:
            return "doi:" + doi
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip().lower()
        if title:
            return "title:" + title
        external = str(item.get("external_id") or "").strip().lower()
        return "external:" + external if external else ""

    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    max_rank = max((len(items) for _, items in task_results), default=0)
    for rank in range(max_rank):
        for task_id, items in task_results:
            if rank >= len(items):
                continue
            item = dict(items[rank])
            key = key_for(item)
            if not key:
                continue
            if key not in merged:
                item["_retrieval_tasks"] = [task_id]
                merged[key] = item
                order.append(key)
                continue
            current = merged[key]
            current["_retrieval_tasks"] = list(dict.fromkeys(
                [*(current.get("_retrieval_tasks") or []), task_id]
            ))
            for field in ("authors", "landing_url", "publisher", "publication_year", "external_id", "provider"):
                if not current.get(field) and item.get(field):
                    current[field] = item[field]
            incoming_abstract = str(item.get("abstract") or "")
            current_abstract = str(current.get("abstract") or "")
            if len(incoming_abstract) > len(current_abstract):
                current["abstract"] = incoming_abstract

    return [merged[key] for key in order[:cap]]
