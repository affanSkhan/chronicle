from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import AuditEvent, Claim, Conclusion, ConclusionEvidenceRelation, EvidenceRelation, Paper, PaperDependency, PaperVersion, Passage, ReportVersion, SourceEvent, SourceStatusCheck, Study, UploadedPdfBlob, User
from app.services.pdf_ingestion import extract_pdf
from app.services.private_object_storage import delete_original_pdf, store_original_pdf
from app.services.audit import record_audit_event

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(get_current_user)])
settings = get_settings()


@router.post("/upload", status_code=201)
async def upload_pdf(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Upload a PDF file.")
    serverless_runtime = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
    environment = str(getattr(settings, "environment", "development")).strip().lower()
    def _has_secret(value: object) -> bool:
        getter = getattr(value, "get_secret_value", None)
        raw = getter() if callable(getter) else value
        return bool(str(raw or "").strip())
    private_storage_configured = all([
        str(getattr(settings, "object_storage_endpoint_url", "") or "").strip(),
        str(getattr(settings, "object_storage_bucket", "") or "").strip(),
        _has_secret(getattr(settings, "object_storage_access_key_id", None)),
        _has_secret(getattr(settings, "object_storage_secret_access_key", None)),
    ])
    database_fallback = not private_storage_configured and (
        serverless_runtime or environment in {"production", "prod"}
    )
    upload_limit_mb = min(max(1, int(settings.max_upload_mb)), 3) if (serverless_runtime or database_fallback) else int(settings.max_upload_mb)
    max_bytes = upload_limit_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"PDF exceeds the {upload_limit_mb} MB upload limit for this deployment.")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="The uploaded file does not have a valid PDF signature.")

    file_hash = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Paper).where(Paper.file_sha256 == file_hash, Paper.owner_user_id == current_user.id))
    if existing:
        version = db.scalar(select(PaperVersion).where(PaperVersion.paper_id == existing.id).order_by(PaperVersion.retrieved_at.desc()))
        return {
            "paper_id": existing.id,
            "title": existing.title,
            "duplicate_upload": True,
            "message": "This exact PDF was already ingested; no duplicate passages were created.",
        }

    try:
        extracted = extract_pdf(
            data,
            max_pages=settings.max_pdf_pages,
            enable_ocr=settings.enable_pdf_ocr,
            ocr_max_pages=settings.pdf_ocr_max_pages,
            ocr_dpi=settings.pdf_ocr_dpi,
            ocr_min_text_chars=settings.pdf_ocr_min_text_chars,
            ocr_language=settings.pdf_ocr_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    raw_name = Path(file.filename or "uploaded-document.pdf").name
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(raw_name).stem).strip(".-_")[:80] or "document"
    try:
        stored_original = store_original_pdf(
            data,
            owner_id=current_user.id,
            sha256=file_hash,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Private PDF storage failed. No upload record was created.") from exc

    title = extracted.title or safe_stem
    author_list = [extracted.author] if extracted.author else []
    paper = Paper(
        owner_user_id=current_user.id,
        title=title,
        authors=author_list,
        publisher="User-uploaded PDF",
        source_provider="upload",
        external_id=file_hash,
        landing_url=None,
        source_file_path=stored_original["reference"],
        file_sha256=file_hash,
    )
    db.add(paper)
    db.flush()
    version = PaperVersion(
        paper_id=paper.id,
        version_label=f"upload-{file_hash[:12]}",
        publication_status="unknown",
        metadata_snapshot={
            "original_filename": raw_name,
            "sha256": file_hash,
            "storage_backend": stored_original["backend"],
            "original_bytes_durable": stored_original["durable"],
            "storage_object_key": stored_original.get("object_key"),
            "page_count": extracted.page_count,
            "text_characters": extracted.text_characters,
            "extraction_method": extracted.extraction_method,
            "ocr_attempted_pages": extracted.ocr_attempted_pages,
            "ocr_pages": extracted.ocr_pages,
            "ocr_failed_page_numbers": extracted.ocr_failed_page_numbers or [],
            "low_text_page_numbers": extracted.low_text_page_numbers or [],
            "text_coverage_ratio": extracted.text_coverage_ratio,
            "extraction_warnings": extracted.warnings or [],
        },
    )
    db.add(version)
    db.flush()
    if stored_original["backend"] == "database":
        db.add(UploadedPdfBlob(paper_version_id=version.id, sha256=file_hash, data=data))

    passages = [
        Passage(
            paper_version_id=version.id,
            section_title=passage.section_title,
            page_number=passage.page_number,
            text=passage.text,
            char_start=passage.char_start,
            char_end=passage.char_end,
            text_hash=passage.text_hash,
            extraction_method=passage.extraction_method,
        )
        for passage in extracted.passages
    ]
    db.add_all(passages)
    db.commit()
    db.refresh(paper)
    db.refresh(version)

    return {
        "paper_id": paper.id,
        "paper_version_id": version.id,
        "title": paper.title,
        "page_count": extracted.page_count,
        "text_characters": extracted.text_characters,
        "passages_created": len(passages),
        "extraction_method": extracted.extraction_method,
        "ocr_attempted_pages": extracted.ocr_attempted_pages,
        "ocr_pages": extracted.ocr_pages,
        "ocr_failed_page_numbers": extracted.ocr_failed_page_numbers or [],
        "low_text_page_numbers": extracted.low_text_page_numbers or [],
        "text_coverage_ratio": extracted.text_coverage_ratio,
        "extraction_warnings": extracted.warnings or [],
        "sha256": file_hash,
        "storage_backend": stored_original["backend"],
        "binary_storage_durable": stored_original["durable"],
        "duplicate_upload": False,
        "note": (
            "Text passages and original PDF bytes are stored in a separate private database table."
            if stored_original["backend"] == "database" else
            "Text passages are persisted in PostgreSQL and original PDF bytes are stored in a private S3-compatible object bucket."
            if stored_original["backend"] == "s3" else
            "Text passages and original PDF bytes use local filesystem storage for development only."
        ),
    }


@router.get("/papers/{paper_id}/passages")
def list_passages(
    paper_id: str,
    page: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_user_id == current_user.id))
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    limit = max(1, min(limit, 250))
    versions = db.scalars(select(PaperVersion).where(PaperVersion.paper_id == paper_id)).all()
    version_ids = [v.id for v in versions]
    if not version_ids:
        return {"paper_id": paper_id, "passages": [], "count": 0}
    statement = select(Passage).where(Passage.paper_version_id.in_(version_ids))
    if page is not None:
        statement = statement.where(Passage.page_number == page)
    results = list(db.scalars(statement.order_by(Passage.page_number, Passage.char_start).limit(limit)).all())
    return {
        "paper_id": paper_id,
        "count": len(results),
        "passages": [{
            "id": row.id,
            "paper_version_id": row.paper_version_id,
            "page_number": row.page_number,
            "section_title": row.section_title,
            "text": row.text,
            "text_hash": row.text_hash,
            "extraction_method": row.extraction_method,
        } for row in results],
    }


@router.delete("/papers/{paper_id}")
def permanently_delete_uploaded_pdf(
    paper_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Permanently remove an uploaded PDF, its passage data, and derived report text.

    Older report versions in impacted runs are retained as records but redacted so
    they cannot keep reproducing deleted PDF-derived material. Claims with no
    surviving passage evidence are deleted; claims with other evidence are marked
    for review rather than silently retaining a confident assessment.
    """
    paper = db.scalar(select(Paper).where(
        Paper.id == paper_id,
        Paper.owner_user_id == current_user.id,
        Paper.source_provider == "upload",
    ))
    if paper is None:
        raise HTTPException(status_code=404, detail="Uploaded PDF not found in your library.")

    version_ids = set(db.scalars(
        select(PaperVersion.id).where(PaperVersion.paper_id == paper.id)
    ).all())
    passage_ids = set(db.scalars(
        select(Passage.id).where(Passage.paper_version_id.in_(version_ids))
    ).all()) if version_ids else set()

    linked_relations = list(db.scalars(
        select(EvidenceRelation).where(EvidenceRelation.passage_id.in_(passage_ids))
    ).all()) if passage_ids else []
    linked_claim_ids = {relation.claim_id for relation in linked_relations}
    linked_claims = list(db.scalars(
        select(Claim).where(Claim.id.in_(linked_claim_ids))
    ).all()) if linked_claim_ids else []
    all_claim_relations = list(db.scalars(
        select(EvidenceRelation).where(EvidenceRelation.claim_id.in_(linked_claim_ids))
    ).all()) if linked_claim_ids else []
    surviving_passages_by_claim: dict[str, set[str]] = {}
    for relation in all_claim_relations:
        if relation.passage_id and relation.passage_id not in passage_ids and relation.reviewer_status != "rejected":
            surviving_passages_by_claim.setdefault(relation.claim_id, set()).add(relation.passage_id)
    # Permanently remove every claim that referenced the PDF, plus claims that
    # explicitly depend on those claims. A surviving second citation is not enough
    # to prove the text itself contains no information from the deleted document.
    claims_to_delete = set(linked_claim_ids)
    changed = True
    while changed:
        dependent_ids = set(db.scalars(select(EvidenceRelation.claim_id).where(
            EvidenceRelation.related_claim_id.in_(claims_to_delete),
            EvidenceRelation.relation_type == "depends_on",
        )).all()) if claims_to_delete else set()
        before = len(claims_to_delete)
        claims_to_delete.update(dependent_ids)
        changed = len(claims_to_delete) != before
    impacted_run_ids = {claim.run_id for claim in linked_claims}
    if claims_to_delete:
        impacted_run_ids.update(db.scalars(select(Claim.run_id).where(Claim.id.in_(claims_to_delete))).all())

    reports = list(db.scalars(select(ReportVersion)).all())
    for report in reports:
        snapshot = report.evidence_snapshot if isinstance(report.evidence_snapshot, dict) else {}
        snapshot_papers = set(snapshot.get("paper_ids", [])) if isinstance(snapshot.get("paper_ids"), list) else set()
        snapshot_passages = set(snapshot.get("passage_ids", [])) if isinstance(snapshot.get("passage_ids"), list) else set()
        if paper.id in snapshot_papers or bool(passage_ids & snapshot_passages):
            impacted_run_ids.add(report.run_id)

    # Delete the original binary before committing the record purge. A missing local
    # file is accepted because serverless /tmp storage may already have expired.
    try:
        storage_result = delete_original_pdf(
            paper.source_file_path,
            owner_id=current_user.id,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Original PDF storage could not be cleaned up; no database records were deleted.") from exc

    # Remove all relationship rows touching deleted passages or claims, including
    # downstream dependency edges that point at a claim being purged.
    relations_to_delete = list(db.scalars(select(EvidenceRelation).where(or_(
        EvidenceRelation.passage_id.in_(passage_ids) if passage_ids else False,
        EvidenceRelation.claim_id.in_(claims_to_delete) if claims_to_delete else False,
        EvidenceRelation.related_claim_id.in_(claims_to_delete) if claims_to_delete else False,
    ))).all())
    sensitive_target_ids = {paper.id, *version_ids, *passage_ids, *claims_to_delete}
    sensitive_target_ids.update(relation.id for relation in relations_to_delete)
    for relation in relations_to_delete:
        db.delete(relation)
    claims_to_delete_rows = list(db.scalars(select(Claim).where(Claim.id.in_(claims_to_delete))).all()) if claims_to_delete else []
    for claim in claims_to_delete_rows:
        db.delete(claim)

    report_redaction_count = 0
    redacted_at = datetime.now(timezone.utc).isoformat()
    for report in reports:
        if report.run_id not in impacted_run_ids:
            continue
        report.content_markdown = (
            "# Report redacted after source deletion\n\n"
            "This saved report version contained a source or passage derived from a user-uploaded PDF "
            "that was permanently deleted by the owner. Its original text has been removed. "
            "Re-run the research workflow using the remaining authorized sources to create a fresh report."
        )
        report.evidence_snapshot = {
            "redacted": True,
            "redaction_reason": "owner_requested_uploaded_pdf_deletion",
            "redacted_at": redacted_at,
            "run_id": report.run_id,
        }
        report.change_summary = "Report content redacted after an owner-requested source deletion."
        report.review_required = True
        report_redaction_count += 1

    # A redacted report must not leave a second, queryable copy of its conclusion text.
    # Remove report-scoped conclusions and evidence edges for every run whose report
    # was redacted; historical audit entries are retained below in redacted form.
    impacted_report_ids = {report.id for report in reports if report.run_id in impacted_run_ids}
    conclusions_to_delete = list(db.scalars(select(Conclusion).where(or_(
        Conclusion.run_id.in_(impacted_run_ids) if impacted_run_ids else False,
        Conclusion.report_version_id.in_(impacted_report_ids) if impacted_report_ids else False,
    ))).all())
    conclusion_ids_to_delete = {conclusion.id for conclusion in conclusions_to_delete}
    conclusion_edges_to_delete = list(db.scalars(
        select(ConclusionEvidenceRelation).where(
            ConclusionEvidenceRelation.conclusion_id.in_(conclusion_ids_to_delete)
        )
    ).all()) if conclusion_ids_to_delete else []
    for edge in conclusion_edges_to_delete:
        sensitive_target_ids.add(edge.id)
        db.delete(edge)
    for conclusion in conclusions_to_delete:
        sensitive_target_ids.add(conclusion.id)
        db.delete(conclusion)

    for dependency in db.scalars(select(PaperDependency).where(or_(
        PaperDependency.dependent_paper_id == paper.id,
        PaperDependency.depends_on_paper_id == paper.id,
    ))).all():
        sensitive_target_ids.add(dependency.id)
        db.delete(dependency)
    for event in db.scalars(select(SourceEvent).where(SourceEvent.paper_id == paper.id)).all():
        sensitive_target_ids.add(event.id)
        db.delete(event)
    for check in db.scalars(select(SourceStatusCheck).where(SourceStatusCheck.paper_id == paper.id)).all():
        sensitive_target_ids.add(check.id)
        db.delete(check)
    for study in db.scalars(select(Study).where(Study.paper_id == paper.id)).all():
        sensitive_target_ids.add(study.id)
        db.delete(study)

    # Historical audit entries remain as records, but payloads/reasons that could
    # contain source or generated claim text are redacted across impacted runs.
    audit_query = select(AuditEvent).where(or_(
        AuditEvent.target_entity_id.in_(sensitive_target_ids),
        AuditEvent.run_id.in_(impacted_run_ids) if impacted_run_ids else False,
    ))
    for event in db.scalars(audit_query).all():
        event.previous_value = None
        event.new_value = {"redacted": True, "reason": "owner_requested_source_deletion"}
        event.reason = "Details redacted after owner-requested source deletion."

    record_audit_event(
        db,
        actor_user_id=current_user.id,
        run_id=None,
        target_entity_type="uploaded_pdf",
        target_entity_id=paper.id,
        action="uploaded_pdf.permanently_deleted",
        previous_value=None,
        new_value={
            "deleted_passage_count": len(passage_ids),
            "deleted_claim_count": len(claims_to_delete),
            "claims_flagged_for_review": 0,
            "redacted_report_version_count": report_redaction_count,
            "storage_backend": storage_result.get("backend"),
        },
        reason="The owner permanently deleted an uploaded PDF and its derived report text.",
        resolution_status="completed",
    )
    if version_ids:
        for blob in db.scalars(
            select(UploadedPdfBlob).where(UploadedPdfBlob.paper_version_id.in_(version_ids))
        ).all():
            db.delete(blob)

    db.delete(paper)
    db.commit()
    return {
        "deleted": True,
        "paper_id": paper_id,
        "deleted_passage_count": len(passage_ids),
        "deleted_claim_count": len(claims_to_delete),
        "claims_flagged_for_review": 0,
        "redacted_report_version_count": report_redaction_count,
        "original_storage_backend": storage_result.get("backend"),
        "note": "The uploaded PDF and extracted passages were removed. Impacted report versions were redacted; claims with other evidence remain flagged for review.",
    }
