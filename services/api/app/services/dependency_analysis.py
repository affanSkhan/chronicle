"""Explainable source-family summaries from recorded dependency edges.

This module never assumes unlinked papers are independent. It summarizes only
relationships already stored in Chronicle, preserving their provenance.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PaperDependency


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
    family_index = {paper_id: index + 1 for index, group in enumerate(families) for paper_id in group}
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
            "Families are derived only from recorded dependency relationships. An unclustered source is not proven independent; "
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
