from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import (
    Claim, EvidenceRelation, Paper, PaperDependency, PaperVersion, Passage,
    ReportVersion, ResearchRun, SourceEvent, Study, User,
)
from app.schemas.evidence import (
    ClaimCreate, ClaimRead, EvidenceRelationCreate, EvidenceRelationRead, EvidenceRelationReview,
    PaperDependencyCreate, StudyCreate,
)

router = APIRouter(prefix="/evidence", tags=["evidence"], dependencies=[Depends(get_current_user)])


@router.post("/claims", response_model=ClaimRead, status_code=201)
def create_claim(payload: ClaimCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Claim:
    if db.scalar(select(ResearchRun.id).where(ResearchRun.id == payload.run_id, ResearchRun.owner_user_id == current_user.id)) is None:
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
def list_claims(run_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[Claim]:
    if db.scalar(select(ResearchRun.id).where(ResearchRun.id == run_id, ResearchRun.owner_user_id == current_user.id)) is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    return list(db.scalars(select(Claim).where(Claim.run_id == run_id).order_by(Claim.created_at)).all())


@router.get("/claims/{claim_id}/relations", response_model=list[EvidenceRelationRead])
def list_claim_relations(claim_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[EvidenceRelation]:
    claim = db.scalar(select(Claim).join(ResearchRun, Claim.run_id == ResearchRun.id).where(Claim.id == claim_id, ResearchRun.owner_user_id == current_user.id))
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")
    return list(db.scalars(select(EvidenceRelation).where(EvidenceRelation.claim_id == claim_id).order_by(EvidenceRelation.created_at)).all())


@router.post("/claims/{claim_id}/relations", response_model=EvidenceRelationRead, status_code=201)
def add_claim_relation(
    claim_id: str,
    payload: EvidenceRelationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceRelation:
    claim = db.scalar(select(Claim).join(ResearchRun, Claim.run_id == ResearchRun.id).where(Claim.id == claim_id, ResearchRun.owner_user_id == current_user.id))
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    if payload.passage_id:
        if db.get(Passage, payload.passage_id) is None:
            raise HTTPException(status_code=404, detail="Evidence passage not found.")
    if payload.related_claim_id:
        other = db.scalar(select(Claim).join(ResearchRun, Claim.run_id == ResearchRun.id).where(Claim.id == payload.related_claim_id, ResearchRun.owner_user_id == current_user.id))
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


@router.patch("/relations/{relation_id}/review", response_model=EvidenceRelationRead)
def review_evidence_relation(
    relation_id: str,
    payload: EvidenceRelationReview,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceRelation:
    relation = db.scalar(select(EvidenceRelation).join(Claim, EvidenceRelation.claim_id == Claim.id).join(ResearchRun, Claim.run_id == ResearchRun.id).where(EvidenceRelation.id == relation_id, ResearchRun.owner_user_id == current_user.id))
    if relation is None:
        raise HTTPException(status_code=404, detail="Evidence relationship not found.")

    previous_status = relation.reviewer_status
    relation.reviewer_status = payload.reviewer_status
    if payload.reviewer_notes:
        relation.metadata_snapshot = {
            **(relation.metadata_snapshot or {}),
            "human_review": {
                "reviewer_status": payload.reviewer_status,
                "reviewer_notes": payload.reviewer_notes,
            },
        }
    if payload.reviewer_status == "accepted":
        relation.provenance_basis = "human_reviewed"
        assessment_map = {
            "supports": "supported",
            "contradicts": "contradicted",
            "qualifies": "qualified",
            "not_comparable": "not_comparable",
            "insufficient_evidence": "insufficient_evidence",
        }
        claim = db.get(Claim, relation.claim_id)
        if claim is not None and relation.relation_type in assessment_map:
            claim.assessment = assessment_map[relation.relation_type]
            claim.review_required = False
    elif payload.reviewer_status in {"rejected", "needs_review"}:
        claim = db.get(Claim, relation.claim_id)
        if claim is not None:
            claim.review_required = True
            claim.assessment = "needs_review"

    relation.metadata_snapshot = {
        **(relation.metadata_snapshot or {}),
        "review_history": [
            *((relation.metadata_snapshot or {}).get("review_history") or []),
            {
                "previous_status": previous_status,
                "new_status": payload.reviewer_status,
                "notes": payload.reviewer_notes,
            },
        ],
    }
    db.commit()
    db.refresh(relation)
    return relation


@router.post("/paper-dependencies", status_code=201)
def add_paper_dependency(payload: PaperDependencyCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    if payload.dependent_paper_id == payload.depends_on_paper_id:
        raise HTTPException(status_code=422, detail="A paper cannot depend on itself.")
    for paper_id in {payload.dependent_paper_id, payload.depends_on_paper_id}:
        if db.scalar(select(Paper.id).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id)) is None:
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
def get_evidence_graph(run_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.owner_user_id == current_user.id))
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
    latest_report = db.scalar(select(ReportVersion).where(
        ReportVersion.run_id == run_id
    ).order_by(ReportVersion.version_number.desc()))
    if latest_report and isinstance(latest_report.evidence_snapshot, dict):
        snapshot_paper_ids = latest_report.evidence_snapshot.get("paper_ids", [])
        if isinstance(snapshot_paper_ids, list):
            paper_ids.update(item for item in snapshot_paper_ids if isinstance(item, str))

    # Include every retrieved paper version and abstract passage from this run,
    # even before claims have been extracted and human-reviewed.
    if paper_ids:
        versions = list(db.scalars(select(PaperVersion).where(PaperVersion.paper_id.in_(paper_ids))).all())
        version_ids = {version.id for version in versions}
        known_passage_ids = {passage.id for passage in passages}
        if version_ids:
            stored_passages = list(db.scalars(select(Passage).where(Passage.paper_version_id.in_(version_ids))).all())
            for passage in stored_passages:
                if passage.id not in known_passage_ids:
                    passages.append(passage)
                    known_passage_ids.add(passage.id)

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
def create_report_version(run_id: str, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.owner_user_id == current_user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    title = str(payload.get("title", "")).strip()
    content = str(payload.get("content_markdown", "")).strip()
    if len(title) < 2 or len(content) < 8:
        raise HTTPException(status_code=422, detail="Provide a title and report content of at least 8 characters.")
    evidence_snapshot = payload.get("evidence_snapshot") if isinstance(payload.get("evidence_snapshot"), dict) else {}
    paper_ids = evidence_snapshot.get("paper_ids", [])
    if isinstance(paper_ids, list) and paper_ids:
        owned_paper_ids = set(db.scalars(select(Paper.id).where(
            Paper.owner_user_id == current_user.id,
            Paper.id.in_([item for item in paper_ids if isinstance(item, str)]),
        )).all())
        if owned_paper_ids != set(paper_ids):
            raise HTTPException(status_code=422, detail="Evidence snapshot contains a paper outside your account.")
    passage_ids = evidence_snapshot.get("passage_ids", [])
    if isinstance(passage_ids, list) and passage_ids:
        owned_passage_ids = set(db.scalars(
            select(Passage.id)
            .join(PaperVersion, Passage.paper_version_id == PaperVersion.id)
            .join(Paper, PaperVersion.paper_id == Paper.id)
            .where(Paper.owner_user_id == current_user.id, Passage.id.in_([item for item in passage_ids if isinstance(item, str)]))
        ).all())
        if owned_passage_ids != set(passage_ids):
            raise HTTPException(status_code=422, detail="Evidence snapshot contains a passage outside your account.")
    claim_ids = evidence_snapshot.get("claim_ids", [])
    if isinstance(claim_ids, list) and claim_ids:
        owned_claim_ids = set(db.scalars(select(Claim.id).where(
            Claim.run_id == run_id,
            Claim.id.in_([item for item in claim_ids if isinstance(item, str)]),
        )).all())
        if owned_claim_ids != set(claim_ids):
            raise HTTPException(status_code=422, detail="Evidence snapshot contains a claim outside this research run.")

    latest = db.scalar(select(ReportVersion).where(ReportVersion.run_id == run_id).order_by(ReportVersion.version_number.desc()))
    version = ReportVersion(
        run_id=run_id,
        version_number=(latest.version_number + 1) if latest else 1,
        parent_version_id=latest.id if latest else None,
        title=title[:500],
        content_markdown=content,
        evidence_snapshot=evidence_snapshot,
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
def list_report_versions(run_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    if db.scalar(select(ResearchRun.id).where(ResearchRun.id == run_id, ResearchRun.owner_user_id == current_user.id)) is None:
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


@router.get("/runs/{run_id}/passport")
def export_evidence_passport(
    run_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export a reproducible snapshot of the report, evidence records and provenance state."""
    from datetime import datetime, timezone
    from fastapi.responses import JSONResponse

    run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.owner_user_id == current_user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")

    reports = list(db.scalars(select(ReportVersion).where(
        ReportVersion.run_id == run_id
    ).order_by(ReportVersion.version_number)).all())
    latest_report = reports[-1] if reports else None
    report_snapshot = latest_report.evidence_snapshot if latest_report and isinstance(latest_report.evidence_snapshot, dict) else {}
    snapshot_paper_ids = {
        item for item in report_snapshot.get("paper_ids", []) if isinstance(item, str)
    }
    snapshot_passage_ids = {
        item for item in report_snapshot.get("passage_ids", []) if isinstance(item, str)
    }

    claims = list(db.scalars(select(Claim).where(Claim.run_id == run_id).order_by(Claim.created_at)).all())
    claim_ids = {claim.id for claim in claims}
    relations = list(db.scalars(select(EvidenceRelation).where(
        EvidenceRelation.claim_id.in_(claim_ids)
    ).order_by(EvidenceRelation.created_at)).all()) if claim_ids else []
    passage_ids = {relation.passage_id for relation in relations if relation.passage_id}
    passage_ids.update(snapshot_passage_ids)
    passages = list(db.scalars(select(Passage).where(Passage.id.in_(passage_ids))).all()) if passage_ids else []
    version_ids = {passage.paper_version_id for passage in passages}
    paper_ids = set(snapshot_paper_ids)
    if version_ids:
        direct_versions = db.scalars(select(PaperVersion).where(PaperVersion.id.in_(version_ids))).all()
        paper_ids.update(version.paper_id for version in direct_versions)

    # Include the transitive dependency neighborhood so the passport covers
    # related source events and paper records, not just the directly cited source.
    all_dependencies = list(db.scalars(select(PaperDependency)).all())
    dependencies: list[PaperDependency] = []
    changed = True
    while changed:
        changed = False
        for dependency in all_dependencies:
            if dependency in dependencies:
                continue
            if dependency.dependent_paper_id in paper_ids or dependency.depends_on_paper_id in paper_ids:
                dependencies.append(dependency)
                before = len(paper_ids)
                paper_ids.add(dependency.dependent_paper_id)
                paper_ids.add(dependency.depends_on_paper_id)
                if len(paper_ids) != before:
                    changed = True

    versions = list(db.scalars(select(PaperVersion).where(or_(
        PaperVersion.id.in_(version_ids),
        PaperVersion.paper_id.in_(paper_ids),
    ))).all()) if (version_ids or paper_ids) else []
    papers = list(db.scalars(select(Paper).where(Paper.id.in_(paper_ids))).all()) if paper_ids else []
    source_events = list(db.scalars(select(SourceEvent).where(
        SourceEvent.paper_id.in_(paper_ids)
    ).order_by(SourceEvent.observed_at.desc())).all()) if paper_ids else []

    version_by_id = {version.id: version for version in versions}
    paper_by_id = {paper.id: paper for paper in papers}
    passage_by_id = {passage.id: passage for passage in passages}
    relation_by_claim: dict[str, list[EvidenceRelation]] = {}
    for relation in relations:
        relation_by_claim.setdefault(relation.claim_id, []).append(relation)

    def iso(value):
        return value.isoformat() if value else None

    passport = {
        "schema_version": "1.0",
        "passport_generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "run_id": run.id,
            "research_question": run.question,
            "mode": run.mode,
            "status": run.status,
            "run_created_at": iso(run.created_at),
            "configuration_snapshot": run.configuration or {},
        },
        "interpretation_limitations": [
            "This passport captures records available in Chronicle at export time; it is not a guarantee that the searched corpus is exhaustive.",
            "Model-inferred edges and candidate claims are not equivalent to human-verified scientific conclusions.",
            "An absent edge is not evidence that a relationship does not exist.",
            "Source events flag claims and report versions for review; they do not automatically prove dependent claims false.",
            "Abstract-only evidence must not be described as full-text appraisal.",
        ],
        "papers": [{
            "id": paper.id,
            "doi": paper.doi,
            "title": paper.title,
            "authors": paper.authors or [],
            "abstract": paper.abstract,
            "publication_year": paper.publication_year,
            "publisher": paper.publisher,
            "source_provider": paper.source_provider,
            "external_id": paper.external_id,
            "landing_url": paper.landing_url,
            "versions": [{
                "id": version.id,
                "version_label": version.version_label,
                "publication_status": version.publication_status,
                "publication_date": iso(version.publication_date),
                "retrieved_at": iso(version.retrieved_at),
                "status_url": version.status_url,
                "metadata_snapshot": version.metadata_snapshot or {},
            } for version in versions if version.paper_id == paper.id],
        } for paper in papers],
        "claims": [{
            "id": claim.id,
            "statement": claim.statement,
            "scope": claim.scope or {},
            "assessment": claim.assessment,
            "review_required": claim.review_required,
            "uncertainty_notes": claim.uncertainty_notes,
            "created_at": iso(claim.created_at),
            "evidence_relations": [{
                "id": relation.id,
                "relation_type": relation.relation_type,
                "provenance_basis": relation.provenance_basis,
                "reviewer_status": relation.reviewer_status,
                "confidence": relation.confidence,
                "rationale": relation.rationale,
                "related_claim_id": relation.related_claim_id,
                "passage": ({
                    "id": passage_by_id[relation.passage_id].id,
                    "text": passage_by_id[relation.passage_id].text,
                    "page_number": passage_by_id[relation.passage_id].page_number,
                    "section_title": passage_by_id[relation.passage_id].section_title,
                    "text_hash": passage_by_id[relation.passage_id].text_hash,
                    "paper_version_id": passage_by_id[relation.passage_id].paper_version_id,
                    "paper_id": version_by_id[passage_by_id[relation.passage_id].paper_version_id].paper_id,
                } if relation.passage_id in passage_by_id and passage_by_id[relation.passage_id].paper_version_id in version_by_id else None),
            } for relation in relation_by_claim.get(claim.id, [])],
        } for claim in claims],
        "paper_dependencies": [{
            "id": dependency.id,
            "dependent_paper_id": dependency.dependent_paper_id,
            "depends_on_paper_id": dependency.depends_on_paper_id,
            "relation_type": dependency.relation_type,
            "provenance_basis": dependency.provenance_basis,
            "rationale": dependency.rationale,
            "confidence": dependency.confidence,
            "created_at": iso(dependency.created_at),
        } for dependency in dependencies],
        "source_events": [{
            "id": event.id,
            "paper_id": event.paper_id,
            "event_type": event.event_type,
            "event_date": iso(event.event_date),
            "observed_at": iso(event.observed_at),
            "source_url": event.source_url,
            "description": event.description,
            "verification_status": event.verification_status,
            "metadata_snapshot": event.metadata_snapshot or {},
        } for event in source_events],
        "report_versions": [{
            "id": report.id,
            "version_number": report.version_number,
            "parent_version_id": report.parent_version_id,
            "title": report.title,
            "content_markdown": report.content_markdown,
            "evidence_snapshot": report.evidence_snapshot or {},
            "change_summary": report.change_summary,
            "review_required": report.review_required,
            "created_at": iso(report.created_at),
        } for report in reports],
    }

    filename = f"chronicle-evidence-passport-{run_id[:8]}.{ 'json' if format == 'json' else 'md' }"
    if format == "json":
        return JSONResponse(
            content=passport,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    lines = [
        "# Chronicle Evidence Passport",
        "",
        f"- **Research question:** {run.question}",
        f"- **Run ID:** {run.id}",
        f"- **Mode / status:** {run.mode} / {run.status}",
        f"- **Generated at:** {passport['passport_generated_at']}",
        "",
        "## Interpretation limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in passport["interpretation_limitations"])
    lines.extend(["", "## Source papers", ""])
    for paper in passport["papers"]:
        lines.extend([f"### {paper['title']}", ""])
        lines.append(f"- **Authors:** {', '.join(paper['authors']) or 'Unavailable'}")
        lines.append(f"- **Year:** {paper['publication_year'] or 'Unavailable'}")
        if paper["doi"]:
            lines.append(f"- **DOI:** https://doi.org/{paper['doi']}")
        elif paper["landing_url"]:
            lines.append(f"- **Source:** {paper['landing_url']}")
        if paper["abstract"]:
            lines.extend(["", "**Abstract:**", "", paper["abstract"], ""])
        for version in paper["versions"]:
            lines.append(f"- **Version/status:** {version['version_label']} / {version['publication_status']} (retrieved {version['retrieved_at']})")
        lines.append("")
    lines.extend(["## Claims and evidence trace", ""])
    if not passport["claims"]:
        lines.append("No claim records are linked to this run yet.")
    for claim in passport["claims"]:
        lines.extend([f"### {claim['statement']}", "", f"- **Assessment:** {claim['assessment']}", f"- **Review required:** {claim['review_required']}"])
        if claim["scope"]:
            lines.append(f"- **Scope:** {claim['scope']}")
        if claim["uncertainty_notes"]:
            lines.append(f"- **Uncertainty:** {claim['uncertainty_notes']}")
        for relation in claim["evidence_relations"]:
            lines.append(f"- **{relation['relation_type']}** · basis: {relation['provenance_basis']} · review: {relation['reviewer_status']}")
            if relation["rationale"]:
                lines.append(f"  - Rationale: {relation['rationale']}")
            if relation["passage"]:
                passage = relation["passage"]
                lines.append(f"  - Passage ID: {passage['id']} · page: {passage['page_number'] or 'abstract / page unavailable'} · paper: {passage['paper_id']}")
                lines.append("  - Exact text: " + passage["text"].replace("\n", " "))
        lines.append("")
    lines.extend(["## Source dependencies", ""])
    if not passport["paper_dependencies"]:
        lines.append("No paper-dependency relationships are recorded in this export.")
    for dependency in passport["paper_dependencies"]:
        lines.append(f"- {dependency['depends_on_paper_id']} -> {dependency['dependent_paper_id']} ({dependency['relation_type']}; basis: {dependency['provenance_basis']}; confidence: {dependency['confidence']})")
        if dependency["rationale"]:
            lines.append(f"  - Rationale: {dependency['rationale']}")
    lines.extend(["", "## Source events", ""])
    if not passport["source_events"]:
        lines.append("No source events are recorded for the included papers.")
    for event in passport["source_events"]:
        lines.append(f"- **{event['event_type']}** ({event['verification_status']}) for paper {event['paper_id']} observed {event['observed_at']}: {event['description']}")
        if event["source_url"]:
            lines.append(f"  - Source notice: {event['source_url']}")
        summary = (event["metadata_snapshot"] or {}).get("impact_summary")
        if summary:
            lines.append(f"  - Impact summary: {summary}")
    lines.extend(["", "## Report versions", ""])
    if not passport["report_versions"]:
        lines.append("No report versions are saved.")
    for report in passport["report_versions"]:
        lines.extend([f"### Version {report['version_number']}: {report['title']}", "", f"- **Created:** {report['created_at']}", f"- **Review required:** {report['review_required']}"])
        if report["change_summary"]:
            lines.append(f"- **Change summary:** {report['change_summary']}")
        lines.extend(["", report["content_markdown"], ""])
    return Response(
        content="\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/papers/{paper_id}/studies", status_code=201)
def create_study(paper_id: str, payload: StudyCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    if db.scalar(select(Paper.id).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id)) is None:
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
