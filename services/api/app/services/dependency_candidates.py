"""Heuristic candidate links for potentially dependent scholarly sources.

Only high-specificity signals are surfaced: shared named dataset or registry
identifiers, or near-duplicate abstracts. Suggestions are not persisted
automatically and must be confirmed by a researcher.
"""
from __future__ import annotations

import re
from itertools import combinations
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import Paper, PaperDependency, PaperVersion, Passage


_DATASET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("MIMIC-III", re.compile(r"\bmimic[\s-]?iii\b", re.IGNORECASE)),
    ("MIMIC-IV", re.compile(r"\bmimic[\s-]?iv\b", re.IGNORECASE)),
    ("UK Biobank", re.compile(r"\buk\s+biobank\b|\bukb\b", re.IGNORECASE)),
    ("NHANES", re.compile(r"\bnhanes\b", re.IGNORECASE)),
    ("TCGA", re.compile(r"\btcga\b|\bthe cancer genome atlas\b", re.IGNORECASE)),
    ("ADNI", re.compile(r"\badni\b|\balzheimer'?s disease neuroimaging initiative\b", re.IGNORECASE)),
    ("SEER", re.compile(r"\bseer\s+database\b|\bsurveillance,?\s+epidemiology,?\s+and\s+end results\b", re.IGNORECASE)),
    ("Framingham Heart Study", re.compile(r"\bframingham heart study\b", re.IGNORECASE)),
    ("Rotterdam Study", re.compile(r"\brotterdam study\b", re.IGNORECASE)),
    ("PhysioNet", re.compile(r"\bphysionet\b", re.IGNORECASE)),
    ("ImageNet", re.compile(r"\bimagenet\b", re.IGNORECASE)),
    ("CIFAR-10", re.compile(r"\bcifar[\s-]?10\b", re.IGNORECASE)),
    ("MNIST", re.compile(r"\bmnist\b", re.IGNORECASE)),
    ("SQuAD", re.compile(r"\bsquad\b|\bstanford question answering dataset\b", re.IGNORECASE)),
    ("ClinicalTrials.gov registry", re.compile(r"\bnct\d{8}\b", re.IGNORECASE)),
    ("ISRCTN registry", re.compile(r"\bisrctn\s*\d+\b", re.IGNORECASE)),
    ("ChiCTR registry", re.compile(r"\bchictr\d+\b", re.IGNORECASE)),
    ("ACTRN registry", re.compile(r"\bactrn\d+\b", re.IGNORECASE)),
)

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'-]*", re.IGNORECASE)


def _dataset_signals(text: str) -> list[str]:
    return [label for label, pattern in _DATASET_PATTERNS if pattern.search(text or "")]


def _fivegrams(text: str) -> set[tuple[str, ...]]:
    words = [word.lower() for word in _WORD_RE.findall(text or "")]
    if len(words) < 12:
        return set()
    return {tuple(words[index:index + 5]) for index in range(len(words) - 4)}


def _jaccard(left: set[Any], right: set[Any]) -> float:
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def suggest_dependency_candidates(
    db: Session,
    owner_user_id: str,
    limit: int = 30,
    paper_ids: list[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Find source-dependence candidates, optionally restricted to one research run.

    Ownership is enforced by the query. Candidate discovery does not persist graph edges.
    """
    maximum = max(1, min(int(limit), 100))
    requested_ids = sorted(set(paper_ids or [])) if paper_ids is not None else None
    if requested_ids is not None and len(requested_ids) < 2:
        return []
    statement = select(Paper).where(Paper.owner_user_id == owner_user_id)
    if requested_ids is not None:
        statement = statement.where(Paper.id.in_(requested_ids))
    papers = list(db.scalars(
        statement.order_by(Paper.title.asc(), Paper.id.asc()).limit(250)
    ).all())
    if len(papers) < 2:
        return []

    paper_ids = [paper.id for paper in papers]
    text_by_id: dict[str, str] = {
        paper.id: " ".join(part for part in (paper.title, paper.abstract or "") if part)
        for paper in papers
    }
    abstract_by_id = {paper.id: (paper.abstract or "").strip() for paper in papers}

    # Add a bounded sample of extracted PDF text for source records without abstracts.
    versions = list(db.scalars(
        select(PaperVersion).where(PaperVersion.paper_id.in_(paper_ids))
    ).all())
    version_to_paper = {version.id: version.paper_id for version in versions}
    version_ids = list(version_to_paper)
    if version_ids:
        passage_rows = db.execute(
            select(Passage.paper_version_id, Passage.text)
            .where(Passage.paper_version_id.in_(version_ids))
            .order_by(Passage.page_number.asc().nullsfirst(), Passage.char_start.asc().nullsfirst())
            .limit(5000)
        ).all()
        per_paper_chars: dict[str, int] = {}
        for version_id, passage_text in passage_rows:
            paper_id = version_to_paper.get(version_id)
            if not paper_id:
                continue
            current = per_paper_chars.get(paper_id, 0)
            if current >= 12000:
                continue
            piece = re.sub(r"\s+", " ", passage_text or "")[: max(0, 12000 - current)]
            if piece:
                text_by_id[paper_id] = (text_by_id.get(paper_id, "") + " " + piece).strip()
                per_paper_chars[paper_id] = current + len(piece)

    existing = db.scalars(
        select(PaperDependency).where(or_(
            PaperDependency.dependent_paper_id.in_(paper_ids),
            PaperDependency.depends_on_paper_id.in_(paper_ids),
        ))
    ).all()
    existing_pairs = {
        (frozenset((edge.dependent_paper_id, edge.depends_on_paper_id)), edge.relation_type)
        for edge in existing
    }

    signals_by_id = {paper_id: _dataset_signals(text) for paper_id, text in text_by_id.items()}
    grams_by_id = {paper_id: _fivegrams(text) for paper_id, text in abstract_by_id.items()}
    paper_by_id = {paper.id: paper for paper in papers}
    candidates: dict[tuple[str, str], dict[str, Any]] = {}

    for left, right in combinations(papers, 2):
        pair = tuple(sorted((left.id, right.id)))
        shared_signals = sorted(set(signals_by_id.get(left.id, [])) & set(signals_by_id.get(right.id, [])))
        if shared_signals and (frozenset(pair), "same_dataset") not in existing_pairs:
            candidates[pair] = {
                "pair": pair,
                "relation_type": "same_dataset",
                "confidence": 0.88 if any("registry" in signal for signal in shared_signals) else 0.82,
                "signals": [f"shared_identifier:{signal}" for signal in shared_signals],
                "rationale": "Both source records mention the same recognized dataset or study-registry identifier. This suggests possible evidence dependence, but the study context and actual data reuse must be verified.",
            }

        similarity = _jaccard(grams_by_id.get(left.id, set()), grams_by_id.get(right.id, set()))
        if similarity >= 0.68 and (frozenset(pair), "duplicate_or_overlap") not in existing_pairs:
            current = candidates.get(pair)
            duplicate_candidate = {
                "pair": pair,
                "relation_type": "duplicate_or_overlap",
                "confidence": round(min(0.97, max(0.68, similarity)), 3),
                "signals": [f"abstract_fivegram_jaccard:{similarity:.3f}"],
                "rationale": "The abstracts share a high proportion of identical five-word sequences. This may indicate duplicate records or overlapping text, but does not establish that the underlying studies are the same.",
            }
            if current is None or (current["relation_type"] != "same_dataset" and duplicate_candidate["confidence"] > current["confidence"]):
                candidates[pair] = duplicate_candidate

    results: list[dict[str, Any]] = []
    for pair, candidate in candidates.items():
        first_id, second_id = pair
        first, second = paper_by_id[first_id], paper_by_id[second_id]
        results.append({
            "id": f"{candidate['relation_type']}:{first_id}:{second_id}",
            "paper_a_id": first_id,
            "paper_a_title": first.title,
            "paper_a_doi": first.doi,
            "paper_b_id": second_id,
            "paper_b_title": second.title,
            "paper_b_doi": second.doi,
            "relation_type": candidate["relation_type"],
            "provenance_basis": "metadata_inferred",
            "confidence": candidate["confidence"],
            "signals": candidate["signals"],
            "rationale": candidate["rationale"],
            "direction": "symmetric",
        })

    results.sort(key=lambda item: (-item["confidence"], item["relation_type"], item["paper_a_title"].lower(), item["paper_b_title"].lower()))
    return results[:maximum]


def build_dependency_clusters(
    sources: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Group candidate-linked source records without asserting statistical independence."""
    source_by_id = {
        str(source["paper_id"]): source
        for source in sources
        if source.get("paper_id")
    }
    adjacency: dict[str, set[str]] = {paper_id: set() for paper_id in source_by_id}
    candidate_by_pair: dict[frozenset[str], list[dict[str, Any]]] = {}
    for candidate in candidates:
        left = str(candidate.get("paper_a_id") or "")
        right = str(candidate.get("paper_b_id") or "")
        if left not in source_by_id or right not in source_by_id or left == right:
            continue
        adjacency[left].add(right)
        adjacency[right].add(left)
        candidate_by_pair.setdefault(frozenset((left, right)), []).append(candidate)

    visited: set[str] = set()
    clusters: list[dict[str, Any]] = []
    clustered_ids: set[str] = set()
    for start_id in sorted(source_by_id, key=lambda item: (
        str(source_by_id[item].get("title") or "").casefold(), item
    )):
        if start_id in visited:
            continue
        stack = [start_id]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            stack.extend(sorted(adjacency[current] - visited, reverse=True))
        if len(component) < 2:
            continue
        clustered_ids.update(component)
        component_candidates: list[dict[str, Any]] = []
        for pair, pair_candidates in candidate_by_pair.items():
            if pair.issubset(component):
                component_candidates.extend(pair_candidates)
        if not component_candidates:
            continue
        ordered_ids = sorted(component, key=lambda item: (
            str(source_by_id[item].get("title") or "").casefold(), item
        ))
        candidate_ids = sorted({str(item.get("id") or "") for item in component_candidates if item.get("id")})
        clusters.append({
            "cluster_id": "dependency-cluster-" + hashlib.sha256("|".join(sorted(component)).encode("utf-8")).hexdigest()[:12],
            "paper_ids": ordered_ids,
            "paper_titles": [str(source_by_id[item].get("title") or "Untitled source") for item in ordered_ids],
            "source_count": len(ordered_ids),
            "candidate_link_ids": candidate_ids,
            "candidate_link_count": len(component_candidates),
            "relation_types": sorted({str(item.get("relation_type") or "unknown") for item in component_candidates}),
            "signals": sorted({str(signal) for item in component_candidates for signal in item.get("signals", [])}),
            "status": "candidate_requires_human_review",
            "interpretation": "Potentially dependent sources; do not count as statistically independent until the underlying studies and data lineage are reviewed.",
        })
    clusters.sort(key=lambda item: (-item["source_count"], -item["candidate_link_count"], item["cluster_id"]))
    return {
        "status": "heuristic_scan_completed",
        "raw_source_count": len(source_by_id),
        "candidate_link_count": len(candidates),
        "candidate_cluster_count": len(clusters),
        "clustered_source_count": len(clustered_ids),
        "unclustered_source_count": len(set(source_by_id) - clustered_ids),
        "clusters": clusters,
        "interpretation": "Unclustered records are not proven independent. These heuristic clusters are review prompts, not calibrated dependency or independence estimates.",
    }
