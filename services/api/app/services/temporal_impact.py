"""Deterministic, explainable propagation from changed sources to affected claims."""
from collections import deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Claim, EvidenceRelation, PaperDependency, PaperVersion, Passage, ReportVersion


_SYMMETRIC_DEPENDENCY_TYPES = {"same_dataset", "duplicate_or_overlap"}


def impacted_papers(db: Session, paper_id: str) -> tuple[set[str], dict[str, list[str]]]:
    """Return source + potentially affected papers and a reason chain.

    Directed dependencies are traversed from a source to records that depend on
    it. The relation types same_dataset and duplicate_or_overlap are symmetric:
    neither endpoint is inherently upstream, so both directions can be flagged.
    This is a review prompt, not automatic invalidation of a source or claim.
    """
    impacted = {paper_id}
    reasons: dict[str, list[str]] = {paper_id: ["source_event_on_paper"]}
    queue = deque([paper_id])

    def include(candidate_id: str, relation_type: str, changed_id: str) -> None:
        if candidate_id not in impacted:
            impacted.add(candidate_id)
            reasons[candidate_id] = [f"{relation_type}:{changed_id}"]
            queue.append(candidate_id)
        else:
            reasons.setdefault(candidate_id, []).append(f"{relation_type}:{changed_id}")

    while queue:
        changed_id = queue.popleft()
        outgoing = db.scalars(
            select(PaperDependency).where(PaperDependency.depends_on_paper_id == changed_id)
        ).all()
        for dependency in outgoing:
            include(dependency.dependent_paper_id, dependency.relation_type, changed_id)

        shared_incoming = db.scalars(
            select(PaperDependency).where(
                PaperDependency.dependent_paper_id == changed_id,
                PaperDependency.relation_type.in_(_SYMMETRIC_DEPENDENCY_TYPES),
            )
        ).all()
        for dependency in shared_incoming:
            include(dependency.depends_on_paper_id, dependency.relation_type, changed_id)

    return impacted, reasons


def impacted_claims(db: Session, paper_ids: set[str]) -> tuple[set[str], dict[str, list[str]]]:
    if not paper_ids:
        return set(), {}
    version_ids = set(db.scalars(select(PaperVersion.id).where(PaperVersion.paper_id.in_(paper_ids))).all())
    passage_ids = set(db.scalars(select(Passage.id).where(Passage.paper_version_id.in_(version_ids))).all()) if version_ids else set()
    claim_ids: set[str] = set()
    reasons: dict[str, list[str]] = {}

    if passage_ids:
        links = db.scalars(select(EvidenceRelation).where(EvidenceRelation.passage_id.in_(passage_ids))).all()
        for link in links:
            claim_ids.add(link.claim_id)
            reasons.setdefault(link.claim_id, []).append(f"linked_to_passage:{link.passage_id}")

    # Relations with relation_type='depends_on' mean claim_id depends on related_claim_id.
    queue = deque(claim_ids)
    visited = set(claim_ids)
    while queue:
        source_claim = queue.popleft()
        dependents = db.scalars(select(EvidenceRelation).where(
            EvidenceRelation.related_claim_id == source_claim,
            EvidenceRelation.relation_type == "depends_on",
        )).all()
        for edge in dependents:
            if edge.claim_id not in visited:
                visited.add(edge.claim_id)
                queue.append(edge.claim_id)
                reasons.setdefault(edge.claim_id, []).append(f"depends_on_claim:{source_claim}")
    return visited, reasons


def mark_review_required(db: Session, claim_ids: set[str]) -> int:
    if not claim_ids:
        return 0
    claims = db.scalars(select(Claim).where(Claim.id.in_(claim_ids))).all()
    for claim in claims:
        claim.review_required = True
        if claim.assessment not in {"unassessed", "needs_review"}:
            claim.assessment = "needs_review"
    return len(claims)


def affected_report_runs(db: Session, claim_ids: set[str]) -> set[str]:
    if not claim_ids:
        return set()
    claims = db.scalars(select(Claim).where(Claim.id.in_(claim_ids))).all()
    return {claim.run_id for claim in claims}
