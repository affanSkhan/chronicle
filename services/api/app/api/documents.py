from pathlib import Path
import hashlib
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import Paper, PaperVersion, Passage, User
from app.services.pdf_ingestion import extract_pdf

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(get_current_user)])
settings = get_settings()


@router.post("/upload", status_code=201)
async def upload_pdf(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Upload a PDF file.")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"PDF exceeds the {settings.max_upload_mb} MB upload limit.")
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
        extracted = extract_pdf(data, max_pages=settings.max_pdf_pages)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    raw_name = Path(file.filename or "uploaded-document.pdf").name
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(raw_name).stem).strip(".-_")[:80] or "document"
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_path = upload_dir / f"{file_hash}.pdf"
    stored_path.write_bytes(data)

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
        source_file_path=str(stored_path),
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
            "page_count": extracted.page_count,
            "text_characters": extracted.text_characters,
            "extraction_method": "PyMuPDF",
        },
    )
    db.add(version)
    db.flush()

    passages = [
        Passage(
            paper_version_id=version.id,
            section_title=passage.section_title,
            page_number=passage.page_number,
            text=passage.text,
            char_start=passage.char_start,
            char_end=passage.char_end,
            text_hash=passage.text_hash,
            extraction_method="pymupdf",
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
        "sha256": file_hash,
        "duplicate_upload": False,
        "note": "Text was extracted; no claims have been verified or generated from this PDF.",
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
