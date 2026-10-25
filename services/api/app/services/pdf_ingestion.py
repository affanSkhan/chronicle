"""Local PDF text extraction with bounded OCR fallback and passage chunking."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import re

import fitz
from PIL import Image
import pytesseract


@dataclass(frozen=True)
class ExtractedPassage:
    page_number: int
    section_title: str | None
    text: str
    char_start: int | None
    char_end: int | None
    text_hash: str
    extraction_method: str = "pymupdf"


@dataclass(frozen=True)
class PDFExtraction:
    title: str | None
    author: str | None
    page_count: int
    passages: list[ExtractedPassage]
    text_characters: int
    extraction_method: str = "pymupdf"
    ocr_attempted_pages: int = 0
    ocr_pages: int = 0
    ocr_failed_page_numbers: list[int] | None = None
    low_text_page_numbers: list[int] | None = None
    text_coverage_ratio: float = 1.0
    warnings: list[str] | None = None


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


def _ocr_page(page: fitz.Page, dpi: int, language: str) -> str:
    """OCR a single page. Render resolution is clamped to limit CPU/memory abuse."""
    bounded_dpi = max(72, min(int(dpi), 250))
    scale = bounded_dpi / 72.0
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    try:
        text = pytesseract.image_to_string(image, lang=language, config="--psm 3")
    finally:
        image.close()
    return (text or "").strip()


def extract_pdf(
    data: bytes,
    max_pages: int = 300,
    *,
    enable_ocr: bool = True,
    ocr_max_pages: int = 50,
    ocr_dpi: int = 150,
    ocr_min_text_chars: int = 40,
    ocr_language: str = "eng",
) -> PDFExtraction:
    """Extract a PDF with page anchors; OCR low-text pages under a bounded budget.

    OCR is best-effort and does not imply accurate recognition. Per-page extraction
    methods, coverage, failures, and low-text warnings are returned to the caller.
    """
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
        all_text: list[str] = []
        native_pages = 0
        ocr_attempted_pages = 0
        ocr_pages = 0
        ocr_failed_page_numbers: list[int] = []
        low_text_page_numbers: list[int] = []
        warnings: list[str] = []
        page_with_text_count = 0
        min_chars = max(1, min(int(ocr_min_text_chars), 500))
        ocr_budget = max(0, min(int(ocr_max_pages), 100))

        for index, page in enumerate(document):
            page_number = index + 1
            page_text = page.get_text("text") or ""
            page_method = "pymupdf"
            native_chars = len(page_text.strip())
            if native_chars:
                native_pages += 1

            if native_chars < min_chars:
                low_text_page_numbers.append(page_number)
                if enable_ocr and ocr_attempted_pages < ocr_budget:
                    ocr_attempted_pages += 1
                    try:
                        ocr_text = _ocr_page(page, dpi=ocr_dpi, language=ocr_language)
                        # Keep OCR only when it recovered more characters than native extraction.
                        if len(ocr_text) > native_chars:
                            page_text = ocr_text
                            page_method = "tesseract_ocr"
                            if ocr_text.strip():
                                ocr_pages += 1
                    except Exception:
                        # Do not expose raw OCR engine diagnostics or fail a whole
                        # mixed digital/scanned document because one page failed.
                        ocr_failed_page_numbers.append(page_number)

            if len(page_text.strip()) >= min_chars and page_number in low_text_page_numbers:
                low_text_page_numbers.remove(page_number)
            if page_text.strip():
                page_with_text_count += 1
            all_text.append(page_text)
            for text, start, end in _chunks(page_text):
                passage_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                passages.append(ExtractedPassage(
                    page_number=page_number,
                    section_title=None,
                    text=text,
                    char_start=start,
                    char_end=end,
                    text_hash=passage_hash,
                    extraction_method=page_method,
                ))

        complete_text = "\n".join(all_text)
        if not complete_text.strip():
            if enable_ocr and ocr_attempted_pages:
                raise ValueError(
                    "No readable text could be extracted. OCR was attempted but recovered no text; "
                    "confirm that Tesseract OCR is installed and that the scan is readable."
                )
            raise ValueError(
                "No selectable text was found. This appears to be a scanned PDF; enable OCR or upload a text-based PDF."
            )

        if ocr_failed_page_numbers:
            warnings.append(
                f"OCR could not process {len(ocr_failed_page_numbers)} page(s); inspect those pages manually."
            )
        if low_text_page_numbers:
            warnings.append(
                f"{len(low_text_page_numbers)} page(s) contain little or no searchable text after extraction."
            )
        if ocr_pages:
            warnings.append(
                "OCR text can contain recognition errors; verify extracted passages against the original page image."
            )
        methods = {passage.extraction_method for passage in passages}
        if methods == {"tesseract_ocr"}:
            extraction_method = "tesseract_ocr"
        elif "tesseract_ocr" in methods:
            extraction_method = "mixed"
        else:
            extraction_method = "pymupdf"

        return PDFExtraction(
            title=(metadata.get("title") or "").strip() or None,
            author=(metadata.get("author") or "").strip() or None,
            page_count=len(document),
            passages=passages,
            text_characters=len(complete_text),
            extraction_method=extraction_method,
            ocr_attempted_pages=ocr_attempted_pages,
            ocr_pages=ocr_pages,
            ocr_failed_page_numbers=ocr_failed_page_numbers,
            low_text_page_numbers=low_text_page_numbers,
            text_coverage_ratio=round(page_with_text_count / max(1, len(document)), 3),
            warnings=warnings,
        )
    finally:
        document.close()
