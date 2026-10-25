from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_llm_config, get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import (
    AuditEvent, Claim, EvidenceRelation, Paper, PaperDependency, PaperVersion, Passage,
    ReportVersion, ResearchRun, SourceEvent, SourceStatusCheck, Study, User,
)
from app.services.audit import record_audit_event
from app.services.citation_verification import verify_claim_with_llm
from app.services.dependency_candidates import suggest_dependency_candidates
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
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=claim.run_id,
        target_entity_type="claim",
        target_entity_id=claim.id,
        action="claim.created",
        previous_value=None,
        new_value={"statement": claim.statement, "scope": claim.scope, "assessment": claim.assessment},
        reason="Claim record created in the research workspace.",
    )
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


@router.post("/claims/{claim_id}/verify")
async def verify_claim_citation_support(
    claim_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Assess linked passages against one claim; model output always remains pending human review."""
    claim = db.scalar(
        select(Claim)
        .join(ResearchRun, Claim.run_id == ResearchRun.id)
        .where(Claim.id == claim_id, ResearchRun.owner_user_id == current_user.id)
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    relations = db.scalars(
        select(EvidenceRelation).where(
            EvidenceRelation.claim_id == claim.id,
            EvidenceRelation.passage_id.is_not(None),
            EvidenceRelation.reviewer_status != "rejected",
        )
    ).all()
    passage_ids = {edge.passage_id for edge in relations if edge.passage_id}
    if not passage_ids:
        raise HTTPException(status_code=422, detail="Link at least one source passage before verifying this claim.")

    rows = db.execute(
        select(Passage, Paper.title, Paper.doi)
        .join(PaperVersion, Passage.paper_version_id == PaperVersion.id)
        .join(Paper, PaperVersion.paper_id == Paper.id)
        .where(Passage.id.in_(passage_ids), Paper.owner_user_id == current_user.id)
    ).all()
    passages = [
        {
            "id": passage.id,
            "paper_title": title,
            "doi": doi,
            "page_number": passage.page_number,
            "section_title": passage.section_title,
            "text": passage.text[:8000],
        }
        for passage, title, doi in rows
    ]
    if not passages:
        raise HTTPException(status_code=422, detail="No accessible source passages were found for this claim.")

    settings = get_settings()
    api_key, api_base, model = get_llm_config(settings)
    if not api_key or not model:
        raise HTTPException(
            status_code=503,
            detail="Citation verification requires LLM_API_KEY and LLM_MODEL (or legacy OPENAI_API_KEY and OPENAI_MODEL). No assessment was changed.",
        )

    try:
        result = await verify_claim_with_llm(
            claim_statement=claim.statement,
            claim_scope=claim.scope or {},
            passages=passages,
            api_key=api_key,
            api_base=api_base,
            model=model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="The configured verifier returned an invalid result. No assessment was changed.") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Citation verification failed. No assessment was changed.") from exc

    previous = {
        "assessment": claim.assessment,
        "review_required": claim.review_required,
    }
    claim.assessment = result["verdict"]
    claim.review_required = True
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=claim.run_id,
        target_entity_type="claim",
        target_entity_id=claim.id,
        action="claim.citation_verification_completed",
        previous_value=previous,
        new_value={
            "assessment": claim.assessment,
            "review_required": True,
            "evidence_passage_ids": result["evidence_passage_ids"],
            "rationale": result["rationale"],
            "uncertainty_notes": result["uncertainty_notes"],
            "model": model,
            "provenance_basis": "model_inferred",
        },
        reason="Model-assisted claim-to-passage assessment; a human reviewer must confirm or revise the result.",
        resolution_status="needs_review",
    )
    db.commit()
    return {
        **result,
        "claim_id": claim.id,
        "review_required": True,
        "reviewer_status": "needs_review",
        "provenance_basis": "model_inferred",
        "verifier_model": model,
        "notice": "This is a model-assisted evidence assessment, not proof of scientific truth. Human review is required.",
    }


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
        passage = db.scalar(
            select(Passage)
            .join(PaperVersion, Passage.paper_version_id == PaperVersion.id)
            .join(Paper, PaperVersion.paper_id == Paper.id)
            .where(Passage.id == payload.passage_id, Paper.owner_user_id == current_user.id)
        )
        if passage is None:
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
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=claim.run_id,
        target_entity_type="evidence_relation",
        target_entity_id=relation.id,
        action="evidence_relation.created",
        previous_value=None,
        new_value={
            "claim_id": relation.claim_id,
            "passage_id": relation.passage_id,
            "related_claim_id": relation.related_claim_id,
            "relation_type": relation.relation_type,
            "provenance_basis": relation.provenance_basis,
            "reviewer_status": relation.reviewer_status,
        },
        reason="Evidence relationship added to a claim.",
    )

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
    previous_provenance = relation.provenance_basis
    claim = db.get(Claim, relation.claim_id)
    previous_claim_state = {
        "assessment": claim.assessment,
        "review_required": claim.review_required,
    } if claim is not None else None
    relation.metadata_snapshot = {
        **(relation.metadata_snapshot or {}),
        "original_provenance_basis": (relation.metadata_snapshot or {}).get("original_provenance_basis", previous_provenance),
    }
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
        if claim is not None and relation.relation_type in assessment_map:
            claim.assessment = assessment_map[relation.relation_type]
            claim.review_required = False
    elif payload.reviewer_status in {"rejected", "needs_review"}:
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
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=claim.run_id if claim is not None else None,
        target_entity_type="evidence_relation",
        target_entity_id=relation.id,
        action="evidence_relation.reviewed",
        previous_value={
            "reviewer_status": previous_status,
            "provenance_basis": previous_provenance,
            "claim_state": previous_claim_state,
        },
        new_value={
            "reviewer_status": relation.reviewer_status,
            "provenance_basis": relation.provenance_basis,
            "claim_state": ({
                "assessment": claim.assessment,
                "review_required": claim.review_required,
            } if claim is not None else None),
        },
        reason=payload.reviewer_notes,
        resolution_status=payload.reviewer_status,
    )
    db.commit()
    db.refresh(relation)
    return relation


@router.get("/dependency-candidates")
def list_dependency_candidates(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return heuristic dependency candidates for human adjudication; does not save graph edges."""
    candidates = suggest_dependency_candidates(db, current_user.id, limit=limit)
    return {
        "count": len(candidates),
        "candidates": candidates,
        "note": (
            "These are heuristic suggestions from shared dataset/registry identifiers or near-duplicate abstracts. "
            "They are not verified dependencies or independent-evidence judgments. Confirm study context before saving."
        ),
    }


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
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=None,
        target_entity_type="paper_dependency",
        target_entity_id=edge.id,
        action="paper_dependency.created",
        previous_value=None,
        new_value={
            "dependent_paper_id": edge.dependent_paper_id,
            "depends_on_paper_id": edge.depends_on_paper_id,
            "relation_type": edge.relation_type,
            "provenance_basis": edge.provenance_basis,
            "rationale": edge.rationale,
            "confidence": edge.confidence,
        },
        reason="Source-dependency relationship recorded.",
    )
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

    report_versions = list(db.scalars(
        select(ReportVersion).where(ReportVersion.run_id == run_id).order_by(ReportVersion.version_number.asc())
    ).all())
    latest_report = report_versions[-1] if report_versions else None

    # All report versions may have different source sets after temporal updates.
    paper_ids: set[str] = set()
    for report in report_versions:
        snapshot = report.evidence_snapshot if isinstance(report.evidence_snapshot, dict) else {}
        snapshot_paper_ids = snapshot.get("paper_ids", [])
        if isinstance(snapshot_paper_ids, list):
            paper_ids.update(item for item in snapshot_paper_ids if isinstance(item, str))

    passage_ids = {rel.passage_id for rel in relations if rel.passage_id}
    passages = list(db.scalars(
        select(Passage)
        .join(PaperVersion, Passage.paper_version_id == PaperVersion.id)
        .join(Paper, PaperVersion.paper_id == Paper.id)
        .where(Passage.id.in_(passage_ids), Paper.owner_user_id == current_user.id)
    ).all()) if passage_ids else []
    owned_passage_ids = {passage.id for passage in passages}
    # A malformed or stale cross-tenant relation should not create a dangling edge or expose a source.
    relations = [relation for relation in relations if not relation.passage_id or relation.passage_id in owned_passage_ids]
    version_ids = {passage.paper_version_id for passage in passages}
    versions = list(db.scalars(select(PaperVersion).where(PaperVersion.id.in_(version_ids))).all()) if version_ids else []
    paper_ids.update(version.paper_id for version in versions)

    # Include every retrieved paper version and abstract passage from this run,
    # even before claims have been extracted and human-reviewed.
    if paper_ids:
        versions = list(db.scalars(
            select(PaperVersion)
            .join(Paper, PaperVersion.paper_id == Paper.id)
            .where(PaperVersion.paper_id.in_(paper_ids), Paper.owner_user_id == current_user.id)
        ).all())
        version_ids = {version.id for version in versions}
        known_passage_ids = {passage.id for passage in passages}
        if version_ids:
            stored_passages = list(db.scalars(
                select(Passage)
                .join(PaperVersion, Passage.paper_version_id == PaperVersion.id)
                .join(Paper, PaperVersion.paper_id == Paper.id)
                .where(Passage.paper_version_id.in_(version_ids), Paper.owner_user_id == current_user.id)
            ).all())
            for passage in stored_passages:
                if passage.id not in known_passage_ids:
                    passages.append(passage)
                    known_passage_ids.add(passage.id)

    # Include the transitive paper-dependency neighborhood for the papers
    # referenced by this run's evidence. The relationship basis stays visible.
    owned_paper_ids = set(db.scalars(
        select(Paper.id).where(Paper.owner_user_id == current_user.id)
    ).all())
    all_dependencies = list(db.scalars(
        select(PaperDependency).where(
            PaperDependency.dependent_paper_id.in_(owned_paper_ids),
            PaperDependency.depends_on_paper_id.in_(owned_paper_ids),
        )
    ).all()) if owned_paper_ids else []
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

    papers = list(db.scalars(select(Paper).where(Paper.id.in_(paper_ids), Paper.owner_user_id == current_user.id)).all()) if paper_ids else []
    studies = list(db.scalars(select(Study).join(Paper, Study.paper_id == Paper.id).where(Study.paper_id.in_(paper_ids), Paper.owner_user_id == current_user.id).order_by(Study.created_at.asc())).all()) if paper_ids else []

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
    nodes.extend({
        "id": f"study:{study.id}",
        "type": "study",
        "label": study.study_type or "Study context",
        "paper_id": study.paper_id,
        "source_passage_id": study.source_passage_id,
        "extraction_basis": study.extraction_basis,
        "population": study.population,
        "method": study.method,
        "intervention": study.intervention,
        "outcomes": study.outcomes or [],
        "limitations": study.limitations or [],
    } for study in studies)

    nodes.extend({
        "id": f"report-version:{report.id}",
        "type": "report_version",
        "label": f"{report.title} · v{report.version_number}",
        "report_version_number": report.version_number,
        "review_required": report.review_required,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    } for report in report_versions)
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
    for study in studies:
        edges.append({
            "source": f"paper:{study.paper_id}",
            "target": f"study:{study.id}",
            "type": "has_study_context",
            "provenance_basis": study.extraction_basis,
        })
        if study.source_passage_id:
            edges.append({
                "source": f"passage:{study.source_passage_id}",
                "target": f"study:{study.id}",
                "type": "characterizes_study",
                "provenance_basis": study.extraction_basis,
            })
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
    known_passage_ids = {passage.id for passage in passages}
    known_claim_ids = {claim.id for claim in claims}
    for report in report_versions:
        snapshot = report.evidence_snapshot if isinstance(report.evidence_snapshot, dict) else {}
        report_node_id = f"report-version:{report.id}"
        for claim_id in snapshot.get("claim_ids", []):
            if isinstance(claim_id, str) and claim_id in known_claim_ids:
                edges.append({
                    "source": f"claim:{claim_id}",
                    "target": report_node_id,
                    "type": "included_in",
                    "provenance_basis": "system_recorded",
                })

        synthesis = snapshot.get("model_synthesis")
        if not isinstance(synthesis, dict):
            continue

        findings = synthesis.get("findings", [])
        if isinstance(findings, list):
            for index, finding in enumerate(findings, start=1):
                if not isinstance(finding, dict) or not isinstance(finding.get("statement"), str):
                    continue
                finding_statement = finding["statement"].strip()
                if not finding_statement:
                    continue
                allowed_refs = [
                    ref for ref in (finding.get("evidence_passage_ids") or [])
                    if isinstance(ref, str) and ref in known_passage_ids
                ]
                conclusion_id = f"conclusion:{report.id}:{index}"
                relation_type = finding.get("relation_type")
                if relation_type not in {"supports", "contradicts", "qualifies", "not_comparable"}:
                    relation_type = "qualifies"
                nodes.append({
                    "id": conclusion_id,
                    "type": "conclusion",
                    "label": finding_statement[:1200],
                    "assessment": relation_type,
                    "review_required": True,
                    "provenance_basis": "model_inferred",
                    "rationale": finding.get("context_note") or "Model-generated synthesis finding; researcher review required.",
                    "evidence_passage_ids": allowed_refs,
                })
                edges.append({
                    "source": report_node_id,
                    "target": conclusion_id,
                    "type": "contains_conclusion",
                    "provenance_basis": "system_recorded",
                })
                for passage_id in allowed_refs:
                    edges.append({
                        "source": f"passage:{passage_id}",
                        "target": conclusion_id,
                        "type": relation_type,
                        "provenance_basis": "model_inferred",
                        "reviewer_status": "needs_review",
                        "rationale": finding.get("context_note") or "The report synthesis links this finding to the cited passage; review the original source text.",
                    })

        opportunities = synthesis.get("research_opportunities", [])
        if isinstance(opportunities, list):
            for index, opportunity in enumerate(opportunities, start=1):
                if not isinstance(opportunity, dict) or not isinstance(opportunity.get("question"), str):
                    continue
                question = opportunity["question"].strip()
                if not question:
                    continue
                allowed_refs = [
                    ref for ref in (opportunity.get("evidence_passage_ids") or [])
                    if isinstance(ref, str) and ref in known_passage_ids
                ]
                recommendation_id = f"recommendation:{report.id}:{index}"
                nodes.append({
                    "id": recommendation_id,
                    "type": "recommendation",
                    "label": question[:1200],
                    "review_required": True,
                    "provenance_basis": "model_inferred",
                    "rationale": opportunity.get("rationale"),
                    "evidence_passage_ids": allowed_refs,
                    "prior_art_search_queries": opportunity.get("prior_art_search_queries") or [],
                    "alternative_explanations": opportunity.get("alternative_explanations") or [],
                    "falsification_plan": opportunity.get("falsification_plan"),
                    "review_status": opportunity.get("review_status", "requires_prior_art_review"),
                })
                edges.append({
                    "source": report_node_id,
                    "target": recommendation_id,
                    "type": "proposes_recommendation",
                    "provenance_basis": "system_recorded",
                })
                for passage_id in allowed_refs:
                    edges.append({
                        "source": f"passage:{passage_id}",
                        "target": recommendation_id,
                        "type": "motivates_recommendation",
                        "provenance_basis": "model_inferred",
                        "reviewer_status": "needs_review",
                        "rationale": opportunity.get("rationale") or "The research opportunity was proposed from this passage; confirm the source context.",
                    })

        # Legacy free-text questions remain explicit recommendations but have
        # no fabricated evidence edges when the model supplied no exact passage IDs.
        legacy_questions = synthesis.get("candidate_research_questions", [])
        if isinstance(legacy_questions, list):
            structured_questions = {
                item.get("question") for item in opportunities
                if isinstance(item, dict) and isinstance(item.get("question"), str)
            } if isinstance(opportunities, list) else set()
            legacy_index = 1
            for legacy_question in legacy_questions:
                if not isinstance(legacy_question, str) or not legacy_question.strip() or legacy_question in structured_questions:
                    continue
                recommendation_id = f"recommendation:{report.id}:legacy:{legacy_index}"
                legacy_index += 1
                nodes.append({
                    "id": recommendation_id,
                    "type": "recommendation",
                    "label": legacy_question.strip()[:1200],
                    "review_required": True,
                    "provenance_basis": "model_inferred",
                    "rationale": "Legacy candidate question has no validated evidence-passage pointers.",
                    "evidence_passage_ids": [],
                    "review_status": "requires_prior_art_review",
                })
                edges.append({
                    "source": report_node_id,
                    "target": recommendation_id,
                    "type": "proposes_recommendation",
                    "provenance_basis": "system_recorded",
                    "reviewer_status": "needs_review",
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
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=run_id,
        target_entity_type="report_version",
        target_entity_id=version.id,
        action="report_version.created",
        previous_value={"parent_version_id": latest.id if latest else None},
        new_value={
            "version_number": version.version_number,
            "title": version.title,
            "review_required": version.review_required,
        },
        reason=payload.get("change_summary") or "Report version saved.",
    )
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


@router.get("/runs/{run_id}/audit")
def list_run_audit_events(
    run_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    run = db.scalar(select(ResearchRun).where(
        ResearchRun.id == run_id,
        ResearchRun.owner_user_id == current_user.id,
    ))
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    rows = db.scalars(
        select(AuditEvent).where(AuditEvent.run_id == run_id)
        .order_by(AuditEvent.created_at.asc()).limit(limit)
    ).all()
    return {
        "run_id": run_id,
        "count": len(rows),
        "events": [{
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "target_entity_type": row.target_entity_type,
            "target_entity_id": row.target_entity_id,
            "action": row.action,
            "previous_value": row.previous_value,
            "new_value": row.new_value,
            "reason": row.reason,
            "resolution_status": row.resolution_status,
            "created_at": row.created_at.isoformat(),
        } for row in rows],
        "note": "Audit events record material operations and review transitions; they complement, rather than replace, the current-state records.",
    }


@router.get("/runs/{run_id}/passport")
def export_evidence_passport(
    run_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|json|pdf)$"),
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
    audit_rows = list(db.scalars(select(AuditEvent).where(
        AuditEvent.run_id == run_id
    ).order_by(AuditEvent.created_at.asc())).all())
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
    status_checks = list(db.scalars(select(SourceStatusCheck).where(
        SourceStatusCheck.paper_id.in_(paper_ids)
    ).order_by(SourceStatusCheck.checked_at.desc())).all()) if paper_ids else []
    studies = list(db.scalars(select(Study).where(Study.paper_id.in_(paper_ids)).order_by(Study.created_at.asc())).all()) if paper_ids else []

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
        "studies": [{
            "id": study.id,
            "paper_id": study.paper_id,
            "source_passage_id": study.source_passage_id,
            "source_passage_text": passage_by_id[study.source_passage_id].text if study.source_passage_id in passage_by_id else None,
            "study_type": study.study_type,
            "population": study.population,
            "method": study.method,
            "intervention": study.intervention,
            "outcomes": study.outcomes or [],
            "limitations": study.limitations or [],
            "extraction_basis": study.extraction_basis,
            "created_at": iso(study.created_at),
        } for study in studies],
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
        "source_status_checks": [{
            "id": check.id,
            "paper_id": check.paper_id,
            "checked_at": iso(check.checked_at),
            "trigger_type": check.trigger_type,
            "outcome": check.outcome,
            "provider_states": check.provider_states or {},
            "signals": check.signals or [],
            "result_hash": check.result_hash,
            "previous_result_hash": check.previous_result_hash,
            "change_detected": check.change_detected,
            "error_message": check.error_message,
        } for check in status_checks],
        "audit_events": [{
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "target_entity_type": row.target_entity_type,
            "target_entity_id": row.target_entity_id,
            "action": row.action,
            "previous_value": row.previous_value,
            "new_value": row.new_value,
            "reason": row.reason,
            "resolution_status": row.resolution_status,
            "created_at": iso(row.created_at),
        } for row in audit_rows],
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

    filename = f"chronicle-evidence-passport-{run_id[:8]}.{ {'json': 'json', 'markdown': 'md', 'pdf': 'pdf'}[format] }"
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
    lines.extend(["## Study context", ""])
    if not passport["studies"]:
        lines.append("No structured study-context records are linked to the included papers.")
    for study in passport["studies"]:
        lines.extend([f"### {study['study_type'] or 'Study context'}", "", f"- **Paper ID:** {study['paper_id']}", f"- **Extraction basis:** {study['extraction_basis']}"])
        if study["source_passage_id"]:
            lines.append(f"- **Source passage ID:** {study['source_passage_id']}")
        if study["population"]:
            lines.append(f"- **Population:** {study['population']}")
        if study["method"]:
            lines.append(f"- **Method:** {study['method']}")
        if study["intervention"]:
            lines.append(f"- **Intervention:** {study['intervention']}")
        if study["outcomes"]:
            lines.append("- **Outcomes:** " + "; ".join(study["outcomes"]))
        if study["limitations"]:
            lines.append("- **Limitations:** " + "; ".join(study["limitations"]))
        if study["source_passage_text"]:
            lines.append("  - **Linked passage text:** " + study["source_passage_text"].replace("\n", " "))
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
    lines.extend(["", "## External source status checks", ""])
    if not passport["source_status_checks"]:
        lines.append("No saved Crossref/OpenAlex status checks are linked to the included papers.")
    for check in passport["source_status_checks"]:
        lines.append(f"- **{check['trigger_type']} check** for paper {check['paper_id']} at {check['checked_at']} (outcome: {check['outcome']}; change detected: {check['change_detected']})")
        lines.append(f"  - Provider states: {check['provider_states']}")
        if check["error_message"]:
            lines.append(f"  - Provider issue: {check['error_message']}")
        for signal in check["signals"]:
            lines.append(f"  - Candidate signal: {signal.get('event_type')} from {signal.get('provider')} — {signal.get('description')}")
            if signal.get("source_url"):
                lines.append(f"    - Notice: {signal['source_url']}")
        lines.append("")
    lines.extend(["", "## Review and audit history", ""])
    if not passport["audit_events"]:
        lines.append("No audit events were recorded for this run.")
    for audit in passport["audit_events"]:
        lines.append(f"- **{audit['action']}** on {audit['target_entity_type']} {audit['target_entity_id']} at {audit['created_at']} (actor: {audit['actor_user_id'] or 'unavailable'}; status: {audit['resolution_status']})")
        if audit["reason"]:
            lines.append(f"  - Reason: {audit['reason']}")
        if audit["previous_value"] is not None or audit["new_value"] is not None:
            lines.append(f"  - Previous: {audit['previous_value']}")
            lines.append(f"  - New: {audit['new_value']}")
    lines.extend(["", "## Report versions", ""])
    if not passport["report_versions"]:
        lines.append("No report versions are saved.")
    for report in passport["report_versions"]:
        lines.extend([f"### Version {report['version_number']}: {report['title']}", "", f"- **Created:** {report['created_at']}", f"- **Review required:** {report['review_required']}"])
        if report["change_summary"]:
            lines.append(f"- **Change summary:** {report['change_summary']}")
        lines.extend(["", report["content_markdown"], ""])
    if format == "pdf":
        # Keep PDF rendering dependency-light: PyMuPDF is already used by the
        # ingestion pipeline. Render the same export content so PDF/Markdown
        # exports cannot silently diverge in scope or interpretation warnings.
        import fitz
        import textwrap

        pdf_document = fitz.open()
        page_width, page_height = 595, 842  # A4 portrait, PDF points
        margin_x, margin_top, margin_bottom = 44, 46, 42
        page = pdf_document.new_page(width=page_width, height=page_height)
        y = margin_top
        content_width = page_width - (2 * margin_x)

        def add_page():
            nonlocal page, y
            page = pdf_document.new_page(width=page_width, height=page_height)
            y = margin_top

        for raw_line in lines:
            line = raw_line.replace("**", "").replace("`", "")
            level = 0
            if line.startswith("# "):
                level, line = 1, line[2:]
            elif line.startswith("## "):
                level, line = 2, line[3:]
            elif line.startswith("### "):
                level, line = 3, line[4:]
            elif line.startswith("- "):
                line = "• " + line[2:]

            # Base-14 Helvetica supports Western text. Replace characters it
            # cannot represent rather than failing the entire passport export.
            line = line.encode("cp1252", errors="replace").decode("cp1252")
            if not line.strip():
                y += 5
                if y > page_height - margin_bottom:
                    add_page()
                continue

            font_size = 17 if level == 1 else 12 if level == 2 else 10 if level == 3 else 8.5
            font_name = "hebo" if level else "helv"
            available_chars = max(36, int(content_width / (font_size * 0.52)))
            wrapped_lines = textwrap.wrap(
                line,
                width=available_chars,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
            ) or [""]
            if level:
                y += 5
            for wrapped in wrapped_lines:
                line_height = font_size * 1.4
                if y + line_height > page_height - margin_bottom:
                    add_page()
                page.insert_text(
                    (margin_x, y),
                    wrapped,
                    fontname=font_name,
                    fontsize=font_size,
                    color=(0.12, 0.16, 0.24),
                )
                y += line_height

        # Add a page number to every page after the content is laid out.
        for page_number, output_page in enumerate(pdf_document, start=1):
            output_page.insert_text(
                (page_width - margin_x - 12, page_height - 18),
                str(page_number),
                fontname="helv",
                fontsize=8,
                color=(0.35, 0.39, 0.46),
            )
        pdf_bytes = pdf_document.tobytes()
        pdf_document.close()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return Response(
        content="\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/papers/{paper_id}/studies", status_code=201)
def create_study(paper_id: str, payload: StudyCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id))
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    if payload.source_passage_id:
        passage = db.scalar(
            select(Passage)
            .join(PaperVersion, Passage.paper_version_id == PaperVersion.id)
            .where(Passage.id == payload.source_passage_id, PaperVersion.paper_id == paper_id)
        )
        if passage is None:
            raise HTTPException(status_code=422, detail="The source passage must belong to this paper.")
    study = Study(
        paper_id=paper_id,
        source_passage_id=payload.source_passage_id,
        study_type=payload.study_type, population=payload.population,
        method=payload.method, intervention=payload.intervention, outcomes=payload.outcomes,
        limitations=payload.limitations, extraction_basis=payload.extraction_basis,
    )
    db.add(study)
    db.flush()
    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=None,
        target_entity_type="study",
        target_entity_id=study.id,
        action="study.context_recorded",
        previous_value=None,
        new_value={
            "paper_id": study.paper_id,
            "source_passage_id": study.source_passage_id,
            "study_type": study.study_type,
            "population": study.population,
            "method": study.method,
            "intervention": study.intervention,
            "outcomes": study.outcomes,
            "limitations": study.limitations,
            "extraction_basis": study.extraction_basis,
        },
        reason="Study context recorded in the paper library.",
        resolution_status="needs_review" if study.extraction_basis == "model_inferred" else "recorded",
    )
    db.commit()
    db.refresh(study)
    return {
        "id": study.id, "paper_id": study.paper_id, "source_passage_id": study.source_passage_id,
        "study_type": study.study_type, "population": study.population, "method": study.method,
        "intervention": study.intervention, "outcomes": study.outcomes,
        "limitations": study.limitations, "extraction_basis": study.extraction_basis,
    }


@router.get("/papers/{paper_id}/studies")
def list_paper_studies(paper_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    if db.scalar(select(Paper.id).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id)) is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    rows = db.scalars(select(Study).where(Study.paper_id == paper_id).order_by(Study.created_at.asc())).all()
    return {
        "paper_id": paper_id,
        "count": len(rows),
        "studies": [{
            "id": item.id,
            "source_passage_id": item.source_passage_id,
            "study_type": item.study_type,
            "population": item.population,
            "method": item.method,
            "intervention": item.intervention,
            "outcomes": item.outcomes,
            "limitations": item.limitations,
            "extraction_basis": item.extraction_basis,
            "created_at": item.created_at.isoformat(),
        } for item in rows],
        "note": "Model-inferred context is a candidate extraction from the linked passage and must be checked against the full paper.",
    }
