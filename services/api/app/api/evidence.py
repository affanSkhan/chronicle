from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entities import (
    Claim, EvidenceRelation, Paper, PaperDependency, PaperVersion, Passage,
    ReportVersion, ResearchRun, Study,
)
from app.schemas.evidence import (
    ClaimCreate, ClaimRead, EvidenceRelationCreate, EvidenceRelationRead,
    PaperDependencyCreate, StudyCreate,
)

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.post("/claims", response_model=ClaimRead, status_code=201)
def create_claim(payload: ClaimCreate, db: Session = Depends(get_db)) -> Claim:
    if db.get(ResearchRun, payload.run_id) is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    claim = Claim(
        run_id=payload.run_id,
        statement=payload.statement.strip(),
        scope=payload.scope,
        uncertainty_notes=payload.uncertainty_notes,
        assessment="unassessed",
        review_required=False,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


@router.get("/runs/{run_id}/claims", response_model=list[ClaimRead])
def list_claims(run_id: str, db: Session = Depends(get_db)) -> list[Claim]:
    if db.get(ResearchRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    return list(db.scalars(select(Claim).where(Claim.run_id == run_id).order_by(Claim.created_at)).all())


@router.get("/claims/{claim_id}/relations", response_model=list[EvidenceRelationRead])
def list_claim_relations(claim_id: str, db: Session = Depends(get_db)) -> list[EvidenceRelation]:
    if db.get(Claim, claim_id) is None:
        raise HTTPException(status_code=404, detail="Claim not found.")
    return list(db.scalars(select(EvidenceRelation).where(EvidenceRelation.claim_id == claim_id).order_by(EvidenceRelation.created_at)).all())


@router.post("/claims/{claim_id}/relations", response_model=EvidenceRelationRead, status_code=201)
def add_claim_relation(
    claim_id: str,
    payload: EvidenceRelationCreate,
    db: Session = Depends(get_db),
) -> EvidenceRelation:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    if payload.passage_id:
        if db.get(Passage, payload.passage_id) is None:
            raise HTTPException(status_code=404, detail="Evidence passage not found.")
    if payload.related_claim_id:
        other = db.get(Claim, payload.related_claim_id)
        if other is None:
            raise HTTPException(status_code=404, detail="Related claim not found.")
        if other.id == claim.id:
            raise HTTPException(status_code=422, detail="A claim cannot relate to itself.")
        if other.run_id != claim.run_id:
            raise HTTPException(status_code=422, detail="Claim-to-claim relationships must be within the same research run.")

    relation = EvidenceRelation(
        claim_id=claim.id,
        passage_id=payload.passage_id,
        related_claim_id=payload.related_claim_id,
        relation_type=payload.relation_type,
        provenance_basis=payload.provenance_basis,
        confidence=payload.confidence,
        reviewer_status=payload.reviewer_status,
        rationale=payload.rationale,
    )
    db.add(relation)

    # Only a human-accepted edge changes the top-level assessment label.
    if payload.reviewer_status == "accepted":
        accepted_assessments = {
            "supports": "supported",
            "contradicts": "contradicted",
            "qualifies": "qualified",
            "not_comparable": "not_comparable",
            "insufficient_evidence": "insufficient_evidence",
        }
        if payload.relation_type in accepted_assessments:
            claim.assessment = accepted_assessments[payload.relation_type]
            claim.review_required = False
    db.commit()
    db.refresh(relation)
    return relation


@router.post("/paper-dependencies", status_code=201)
def add_paper_dependency(payload: PaperDependencyCreate, db: Session = Depends(get_db)) -> dict:
    if payload.dependent_paper_id == payload.depends_on_paper_id:
        raise HTTPException(status_code=422, detail="A paper cannot depend on itself.")
    for paper_id in {payload.dependent_paper_id, payload.depends_on_paper_id}:
        if db.get(Paper, paper_id) is None:
            raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id}")
    existing = db.scalar(select(PaperDependency).where(
        PaperDependency.dependent_paper_id == payload.dependent_paper_id,
        PaperDependency.depends_on_paper_id == payload.depends_on_paper_id,
        PaperDependency.relation_type == payload.relation_type,
    ))
    if existing:
        return {"id": existing.id, "duplicate": True}
    edge = PaperDependency(
        dependent_paper_id=payload.dependent_paper_id,
        depends_on_paper_id=payload.depends_on_paper_id,
        relation_type=payload.relation_type,
        provenance_basis=payload.provenance_basis,
        rationale=payload.rationale,
        confidence=payload.confidence,
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return {
        "id": edge.id,
        "dependent_paper_id": edge.dependent_paper_id,
        "depends_on_paper_id": edge.depends_on_paper_id,
        "relation_type": edge.relation_type,
        "provenance_basis": edge.provenance_basis,
        "rationale": edge.rationale,
        "confidence": edge.confidence,
        "duplicate": False,
    }


@router.get("/runs/{run_id}/graph")
def get_evidence_graph(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    claims = list(db.scalars(select(Claim).where(Claim.run_id == run_id)).all())
    claim_ids = {claim.id for claim in claims}
    relations = list(db.scalars(select(EvidenceRelation).where(
        or_(EvidenceRelation.claim_id.in_(claim_ids), EvidenceRelation.related_claim_id.in_(claim_ids))
    )).all()) if claim_ids else []

    passage_ids = {rel.passage_id for rel in relations if rel.passage_id}
    passages = list(db.scalars(select(Passage).where(Passage.id.in_(passage_ids))).all()) if passage_ids else []
    version_ids = {p.paper_version_id for p in passages}
    versions = list(db.scalars(select(PaperVersion).where(PaperVersion.id.in_(version_ids))).all()) if version_ids else []
    paper_ids = {v.paper_id for v in versions}

    # Include the transitive paper-dependency neighborhood for the papers
    # referenced by this run's evidence. The relationship basis stays visible.
    all_dependencies = list(db.scalars(select(PaperDependency)).all())
    relevant_dependencies: list[PaperDependency] = []
    changed = True
    while changed:
        changed = False
        for dependency in all_dependencies:
            if dependency in relevant_dependencies:
                continue
            if dependency.dependent_paper_id in paper_ids or dependency.depends_on_paper_id in paper_ids:
                relevant_dependencies.append(dependency)
                before = len(paper_ids)
                paper_ids.add(dependency.dependent_paper_id)
                paper_ids.add(dependency.depends_on_paper_id)
                if len(paper_ids) != before:
                    changed = True

    papers = list(db.scalars(select(Paper).where(Paper.id.in_(paper_ids))).all()) if paper_ids else []

    nodes: list[dict] = [{
        "id": f"claim:{c.id}", "type": "claim", "label": c.statement,
        "assessment": c.assessment, "review_required": c.review_required
    } for c in claims]
    nodes.extend({
        "id": f"passage:{p.id}", "type": "passage", "label": p.text[:180],
        "page_number": p.page_number, "paper_version_id": p.paper_version_id
    } for p in passages)
    nodes.extend({
        "id": f"paper-version:{v.id}", "type": "paper_version",
        "label": v.version_label, "publication_status": v.publication_status, "paper_id": v.paper_id
    } for v in versions)
    nodes.extend({
        "id": f"paper:{p.id}", "type": "paper", "label": p.title, "doi": p.doi
    } for p in papers)
    edges: list[dict] = []
    for relation in relations:
        if relation.passage_id:
            source, target = f"passage:{relation.passage_id}", f"claim:{relation.claim_id}"
        else:
            source, target = f"claim:{relation.claim_id}", f"claim:{relation.related_claim_id}"
        edges.append({
            "id": relation.id, "source": source, "target": target,
            "type": relation.relation_type, "provenance_basis": relation.provenance_basis,
            "reviewer_status": relation.reviewer_status, "confidence": relation.confidence,
            "rationale": relation.rationale,
        })
    for passage in passages:
        edges.append({"source": f"paper-version:{passage.paper_version_id}", "target": f"passage:{passage.id}", "type": "contains"})
    for version in versions:
        edges.append({"source": f"paper:{version.paper_id}", "target": f"paper-version:{version.id}", "type": "has_version"})
    for dependency in relevant_dependencies:
        edges.append({
            "id": dependency.id,
            "source": f"paper:{dependency.depends_on_paper_id}",
            "target": f"paper:{dependency.dependent_paper_id}",
            "type": dependency.relation_type,
            "provenance_basis": dependency.provenance_basis,
            "confidence": dependency.confidence,
            "rationale": dependency.rationale,
        })
    return {
        "run_id": run_id, "nodes": nodes, "edges": edges,
        "note": "Only persisted relationships are shown. Missing edges are not evidence that a relationship does not exist.",
    }


@router.post("/runs/{run_id}/reports", status_code=201)
def create_report_version(run_id: str, payload: dict, db: Session = Depends(get_db)) -> dict:
    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    title = str(payload.get("title", "")).strip()
    content = str(payload.get("content_markdown", "")).strip()
    if len(title) < 2 or len(content) < 8:
        raise HTTPException(status_code=422, detail="Provide a title and report content of at least 8 characters.")
    latest = db.scalar(select(ReportVersion).where(ReportVersion.run_id == run_id).order_by(ReportVersion.version_number.desc()))
    version = ReportVersion(
        run_id=run_id,
        version_number=(latest.version_number + 1) if latest else 1,
        parent_version_id=latest.id if latest else None,
        title=title[:500],
        content_markdown=content,
        evidence_snapshot=payload.get("evidence_snapshot") if isinstance(payload.get("evidence_snapshot"), dict) else {},
        change_summary=payload.get("change_summary"),
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return {
        "id": version.id, "run_id": version.run_id, "version_number": version.version_number,
        "parent_version_id": version.parent_version_id, "title": version.title,
        "content_markdown": version.content_markdown, "evidence_snapshot": version.evidence_snapshot,
        "change_summary": version.change_summary, "review_required": version.review_required,
        "created_at": version.created_at.isoformat(),
    }


@router.get("/runs/{run_id}/reports")
def list_report_versions(run_id: str, db: Session = Depends(get_db)) -> list[dict]:
    if db.get(ResearchRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    rows = db.scalars(select(ReportVersion).where(ReportVersion.run_id == run_id).order_by(ReportVersion.version_number.desc())).all()
    return [{
        "id": row.id, "run_id": row.run_id, "version_number": row.version_number,
        "parent_version_id": row.parent_version_id, "title": row.title,
        "content_markdown": row.content_markdown,
        "evidence_snapshot": row.evidence_snapshot,
        "change_summary": row.change_summary, "review_required": row.review_required,
        "created_at": row.created_at.isoformat(),
    } for row in rows]


@router.post("/papers/{paper_id}/studies", status_code=201)
def create_study(paper_id: str, payload: StudyCreate, db: Session = Depends(get_db)) -> dict:
    if db.get(Paper, paper_id) is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    study = Study(
        paper_id=paper_id, study_type=payload.study_type, population=payload.population,
        method=payload.method, intervention=payload.intervention, outcomes=payload.outcomes,
        limitations=payload.limitations, extraction_basis=payload.extraction_basis,
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return {
        "id": study.id, "paper_id": study.paper_id, "study_type": study.study_type,
        "population": study.population, "method": study.method,
        "intervention": study.intervention, "outcomes": study.outcomes,
        "limitations": study.limitations, "extraction_basis": study.extraction_basis,
    }
