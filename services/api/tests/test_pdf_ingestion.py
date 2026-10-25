import io

import fitz
from PIL import Image

from app.services import pdf_ingestion


def make_scanned_pdf(page_count: int = 1) -> bytes:
    png_buffer = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(png_buffer, format="PNG")
    png_data = png_buffer.getvalue()
    document = fitz.open()
    for _ in range(page_count):
        page = document.new_page(width=300, height=300)
        page.insert_image(page.rect, stream=png_data)
    data = document.tobytes()
    document.close()
    return data


def test_scanned_pdf_uses_bounded_ocr_and_records_method(monkeypatch) -> None:
    calls = []

    def fake_ocr(image, lang, config):
        calls.append((lang, config))
        return "OCR recovered a readable scientific abstract with outcomes, methods, and limitations."

    monkeypatch.setattr(pdf_ingestion.pytesseract, "image_to_string", fake_ocr)
    extraction = pdf_ingestion.extract_pdf(
        make_scanned_pdf(),
        enable_ocr=True,
        ocr_max_pages=2,
        ocr_dpi=150,
        ocr_min_text_chars=40,
    )

    assert len(calls) == 1
    assert extraction.extraction_method == "tesseract_ocr"
    assert extraction.ocr_attempted_pages == 1
    assert extraction.ocr_pages == 1
    assert extraction.text_coverage_ratio == 1.0
    assert extraction.passages
    assert extraction.passages[0].extraction_method == "tesseract_ocr"
    assert "recognition errors" in " ".join(extraction.warnings or [])


def test_mixed_pdf_records_native_and_ocr_methods_by_page(monkeypatch) -> None:
    png_buffer = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(png_buffer, format="PNG")
    png_data = png_buffer.getvalue()
    document = fitz.open()
    native_page = document.new_page(width=300, height=300)
    native_page.insert_text((40, 60), "This native page contains enough selectable text to skip the OCR fallback.")
    scanned_page = document.new_page(width=300, height=300)
    scanned_page.insert_image(scanned_page.rect, stream=png_data)
    payload = document.tobytes()
    document.close()

    monkeypatch.setattr(pdf_ingestion.pytesseract, "image_to_string", lambda image, lang, config: "OCR recovered the second scanned page text with enough details for extraction.")
    extraction = pdf_ingestion.extract_pdf(payload, ocr_min_text_chars=40)

    assert extraction.extraction_method == "mixed"
    assert extraction.ocr_pages == 1
    methods_by_page = {passage.page_number: passage.extraction_method for passage in extraction.passages}
    assert methods_by_page[1] == "pymupdf"
    assert methods_by_page[2] == "tesseract_ocr"


def test_scanned_pdf_with_unavailable_ocr_returns_actionable_error(monkeypatch) -> None:
    def unavailable(image, lang, config):
        raise RuntimeError("The tesseract executable is not installed.")

    monkeypatch.setattr(pdf_ingestion.pytesseract, "image_to_string", unavailable)
    try:
        pdf_ingestion.extract_pdf(make_scanned_pdf(), enable_ocr=True)
    except ValueError as exc:
        assert "Tesseract OCR is installed" in str(exc)
    else:
        raise AssertionError("A scanned PDF with no recoverable text should be rejected with a useful message.")


def test_ocr_budget_is_respected_and_low_text_pages_are_reported(monkeypatch) -> None:
    calls = []
    def fake_ocr(image, lang, config):
        calls.append(1)
        return "OCR returned text for only the first page."

    monkeypatch.setattr(pdf_ingestion.pytesseract, "image_to_string", fake_ocr)
    extraction = pdf_ingestion.extract_pdf(
        make_scanned_pdf(page_count=3),
        enable_ocr=True,
        ocr_max_pages=1,
        ocr_min_text_chars=40,
    )
    assert len(calls) == 1
    assert extraction.ocr_attempted_pages == 1
    assert extraction.ocr_pages == 1
    assert extraction.low_text_page_numbers == [2, 3]
    assert extraction.text_coverage_ratio == 1.0
    assert any("little or no searchable text" in warning for warning in extraction.warnings or [])
