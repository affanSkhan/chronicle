"""Local PDF text extraction and passage chunking."""
import hashlib
import re
from dataclasses import dataclass

import fitz


@dataclass(frozen=True)
class ExtractedPassage:
    page_number: int
    section_title: str | None
    text: str
    char_start: int | None
    char_end: int | None
    text_hash: str


@dataclass(frozen=True)
class PDFExtraction:
    title: str | None
    author: str | None
    page_count: int
    passages: list[ExtractedPassage]
    text_characters: int


def _chunks(text: str, size: int = 1100, overlap: int = 140) -> list[tuple[str, int, int]]:
    normalized = re.sub(r"[ \t]+", " ", text)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    if not normalized:
        return []
    chunks = []
    start = 0
    length = len(normalized)
    while start < length:
        end = min(length, start + size)
        if end < length:
            # Prefer sentence/paragraph boundaries where available.
            boundary = max(normalized.rfind(". ", start + size // 2, end), normalized.rfind("\n", start + size // 2, end))
            if boundary > start:
                end = boundary + 1
        segment = normalized[start:end].strip()
        if segment:
            actual_start = start + len(normalized[start:end]) - len(normalized[start:end].lstrip())
            chunks.append((segment, actual_start, end))
        if end >= length:
            break
        start = max(start + 1, end - overlap)
    return chunks


def extract_pdf(data: bytes, max_pages: int = 300) -> PDFExtraction:
    if not data.startswith(b"%PDF-"):
        raise ValueError("The uploaded file does not have a valid PDF signature.")
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("The PDF could not be opened. It may be damaged or password-protected.") from exc

    try:
        if len(document) > max_pages:
            raise ValueError(f"PDF exceeds the {max_pages}-page limit.")
        metadata = document.metadata or {}
        passages: list[ExtractedPassage] = []
        all_text = []
        for index, page in enumerate(document):
            page_text = page.get_text("text") or ""
            all_text.append(page_text)
            for text, start, end in _chunks(page_text):
                passage_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                passages.append(ExtractedPassage(
                    page_number=index + 1,
                    section_title=None,
                    text=text,
                    char_start=start,
                    char_end=end,
                    text_hash=passage_hash,
                ))
        complete_text = "\n".join(all_text)
        if not complete_text.strip():
            raise ValueError("No selectable text was found. Scanned PDFs need OCR, which is not enabled in this version.")
        return PDFExtraction(
            title=(metadata.get("title") or "").strip() or None,
            author=(metadata.get("author") or "").strip() or None,
            page_count=len(document),
            passages=passages,
            text_characters=len(complete_text),
        )
    finally:
        document.close()
