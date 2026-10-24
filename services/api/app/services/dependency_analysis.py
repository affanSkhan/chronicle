"""Explainable source-family summaries from recorded and candidate dependency edges.

Heuristic relationships are persisted as metadata-inferred candidates and require
human review. Absence of a detected link is never treated as source independence.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import re
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.entities import PaperDependency
from app.services.audit import record_audit_event


_IDENTIFIER_PATTERNS = [
    ("trial_registry_id", re.compile(r"\b(?:NCT\d{8}|ISRCTN\d{6,}|ACTRN\d{14}|ChiCTR[A-Za-z0-9]+|EUCTR\d{4}-\d{6}-\d{2})\b", re.I)),
    ("dataset_doi", re.compile(r"\b10\.(?:5061/dryad\.[A-Za-z0-9._-]+|5281/zenodo\.\d+)\b", re.I)),
]
_KNOWN_DATASET_PATTERNS = [
    ("dataset:mimic", re.compile(r"\bMIMIC(?:[- ]?(?:III|IV))?\b", re.I)),
    ("dataset:uk-biobank", re.compile(r"\bUK\s+Biobank\b", re.I)),
    ("dataset:all-of-us", re.compile(r"\bAll\s+of\s+Us\s+(?:Research\s+)?Program\b", re.I)),
    ("dataset:tcga", re.compile(r"\b(?:The\s+Cancer\s+Genome\s+Atlas|TCGA)\b", re.I)),
    ("dataset:seer", re.compile(r"\bSEER\s+(?:database|program|registry)\b", re.I)),
    ("dataset:imagenet", re.compile(r"\bImageNet\b", re.I)),
    ("dataset:mnist", re.compile(r"\bMNIST\b", re.I)),
    ("dataset:cifar10", re.compile(r"\bCIFAR[- ]?10\b", re.I)),
    ("dataset:cifar100", re.compile(r"\bCIFAR[- ]?100\b", re.I)),
    ("dataset:physionet", re.compile(r"\bPhysioNet\b", re.I)),
    ("dataset:eicu", re.compile(r"\beICU\b", re.I)),
    ("dataset:nhanes", re.compile(r"\bNHANES\b", re.I)),
]


def _shared_signals(item: dict[str, Any]) -> set[str]:
    text = " ".join(str(item.get(key) or "") for key in ("title", "abstract"))
    signals: set[str] = set()
    for signal_type, pattern in _IDENTIFIER_PATTERNS:
        for match in pattern.findall(text):
            signals.add(f"{signal_type}:{match.upper()}")
    for label, pattern in _KNOWN_DATASET_PATTERNS:
        if pattern.search(text):
            signals.add(label)
    return signals


def detect_dependency_candidates(paper_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find candidate overlaps using shared explicit IDs, known dataset names or exact abstracts."""
    normalized = []
    for item in paper_items:
        paper_id = item.get("paper_id") or item.get("id")
        if not paper_id:
            continue
        abstract = re.sub(r"\s+", " ", str(item.get("abstract") or "")).strip()
        normalized.append({
            **item,
            "paper_id": str(paper_id),
            "_signals": _shared_signals(item),
            "_abstract_hash": hashlib.sha256(abstract.lower().encode("utf-8")).hexdigest() if len(abstract) >= 100 else None,
        })

    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    for index, left in enumerate(normalized):
        for right in normalized[index + 1:]:
            shared = sorted(left["_signals"] & right["_signals"])
            relation_type = "same_dataset" if shared else None
            rationale_prefix = (
                "The available title/abstract text shares explicit study/dataset identifier(s)"
                if shared else ""
            )
            if not relation_type and left["_abstract_hash"] and left["_abstract_hash"] == right["_abstract_hash"]:
                relation_type = "duplicate_or_overlap"
                shared = ["exact_normalized_abstract_hash"]
                rationale_prefix = "The normalized abstracts are text-identical across distinct source records"
            if not relation_type:
                continue

            a, b = sorted((left["paper_id"], right["paper_id"]))
            key = (a, b, relation_type)
            existing = candidates.get(key)
            if existing:
                existing["matched_signals"] = sorted(set(existing["matched_signals"]) | set(shared))
                continue
            candidates[key] = {
                "paper_a_id": a,
                "paper_b_id": b,
                "relation_type": relation_type,
                "matched_signals": shared,
                "rationale": (
                    f"{rationale_prefix}: {', '.join(shared)}. "
                    "This is an automated dependency candidate and requires human review; it is not proof of source dependence."
                ),
            }
    return list(candidates.values())


def record_candidate_dependencies(
    db: Session,
    paper_items: list[dict[str, Any]],
    run_id: str,
) -> int:
    """Persist candidate overlap as bidirectional graph edges so either event can surface sibling claims."""
    created = 0
    for candidate in detect_dependency_candidates(paper_items):
        a = candidate["paper_a_id"]
        b = candidate["paper_b_id"]
        relation_type = candidate["relation_type"]
        existing = db.scalar(select(PaperDependency.id).where(
            PaperDependency.relation_type == relation_type,
            or_(
                and_(PaperDependency.dependent_paper_id == a, PaperDependency.depends_on_paper_id == b),
                and_(PaperDependency.dependent_paper_id == b, PaperDependency.depends_on_paper_id == a),
            ),
        ))
        if existing:
            continue

        for dependent, depends_on in ((a, b), (b, a)):
            edge = PaperDependency(
                dependent_paper_id=dependent,
                depends_on_paper_id=depends_on,
                relation_type=relation_type,
                provenance_basis="metadata_inferred",
                rationale=candidate["rationale"],
                confidence=None,
            )
            db.add(edge)
            db.flush()
            record_audit_event(
                db,
                actor_user_id=None,
                run_id=run_id,
                target_entity_type="paper_dependency",
                target_entity_id=edge.id,
                action="paper_dependency.candidate_detected",
                previous_value=None,
                new_value={
                    "dependent_paper_id": dependent,
                    "depends_on_paper_id": depends_on,
                    "relation_type": relation_type,
                    "provenance_basis": "metadata_inferred",
                    "matched_signals": candidate["matched_signals"],
                },
                reason=candidate["rationale"],
                resolution_status="needs_review",
            )
            created += 1
    return created


def summarize_dependency_records(
    paper_items: list[dict[str, Any]],
    dependency_items: list[dict[str, Any]],
) -> dict[str, Any]:
    papers: dict[str, dict[str, Any]] = {}
    for item in paper_items:
        paper_id = item.get("paper_id") or item.get("id")
        if paper_id:
            papers[str(paper_id)] = {
                "id": str(paper_id),
                "title": item.get("title") or "Untitled paper",
                "doi": item.get("doi"),
            }

    parent = {paper_id: paper_id for paper_id in papers}

    def find(paper_id: str) -> str:
        while parent[paper_id] != paper_id:
            parent[paper_id] = parent[parent[paper_id]]
            paper_id = parent[paper_id]
        return paper_id

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    valid_edges: list[dict[str, Any]] = []
    for item in dependency_items:
        dependent = str(item.get("dependent_paper_id") or "")
        depends_on = str(item.get("depends_on_paper_id") or "")
        if not dependent or not depends_on or dependent not in papers or depends_on not in papers:
            continue
        valid_edges.append({
            "id": item.get("id"),
            "dependent_paper_id": dependent,
            "depends_on_paper_id": depends_on,
            "relation_type": item.get("relation_type") or "derived_from",
            "provenance_basis": item.get("provenance_basis") or "metadata_inferred",
            "rationale": item.get("rationale"),
            "confidence": item.get("confidence"),
            "review_status": "human_reviewed" if item.get("provenance_basis") == "human_reviewed" else "candidate",
        })
        union(dependent, depends_on)

    members: dict[str, list[str]] = defaultdict(list)
    for paper_id in papers:
        members[find(paper_id)].append(paper_id)

    families = sorted(members.values(), key=lambda group: (len(group) == 1, sorted(group)[0]))
    clusters = []
    for index, group in enumerate(families, start=1):
        if len(group) < 2:
            continue
        group_set = set(group)
        cluster_edges = [
            edge for edge in valid_edges
            if edge["dependent_paper_id"] in group_set and edge["depends_on_paper_id"] in group_set
        ]
        clusters.append({
            "family_id": f"EF-{index:02d}",
            "paper_ids": sorted(group),
            "papers": sorted((papers[paper_id] for paper_id in group), key=lambda paper: paper["title"].lower()),
            "relationships": cluster_edges,
            "review_required": any(edge["review_status"] != "human_reviewed" for edge in cluster_edges),
        })

    sources_in_clusters = {paper_id for cluster in clusters for paper_id in cluster["paper_ids"]}
    return {
        "raw_source_count": len(papers),
        "declared_dependency_edge_count": len(valid_edges),
        "evidence_family_count_estimate": len(families),
        "sources_in_detected_families": len(sources_in_clusters),
        "unclustered_source_count": len(papers) - len(sources_in_clusters),
        "detected_clusters": clusters,
        "interpretation_note": (
            "Families use recorded or heuristic candidate dependency links only. An unclustered source is not proven independent; "
            "candidate or model-inferred edges are not proof, and confidence values are not calibrated evidence-strength probabilities."
        ),
    }


def build_dependency_summary(db: Session, paper_items: list[dict[str, Any]]) -> dict[str, Any]:
    ids = {str(item.get("paper_id") or item.get("id")) for item in paper_items if item.get("paper_id") or item.get("id")}
    if not ids:
        return summarize_dependency_records(paper_items, [])

    rows = db.scalars(select(PaperDependency).where(
        PaperDependency.dependent_paper_id.in_(ids),
        PaperDependency.depends_on_paper_id.in_(ids),
    )).all()
    dependencies = [{
        "id": row.id,
        "dependent_paper_id": row.dependent_paper_id,
        "depends_on_paper_id": row.depends_on_paper_id,
        "relation_type": row.relation_type,
        "provenance_basis": row.provenance_basis,
        "rationale": row.rationale,
        "confidence": row.confidence,
    } for row in rows]
    return summarize_dependency_records(paper_items, dependencies)
