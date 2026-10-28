import fitz
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import document_storage
from app.api import documents
from app.models.entities import Paper, PaperVersion
from conftest import TestingSessionLocal


def _secret(value: str) -> SimpleNamespace:
    return SimpleNamespace(get_secret_value=lambda: value)


def test_local_storage_is_owner_scoped_and_marked_non_durable(tmp_path) -> None:
    settings = SimpleNamespace(document_storage_backend="local", upload_dir=str(tmp_path))
    result = document_storage.store_uploaded_pdf(
        b"%PDF-test", owner_id="user-123", sha256_hex="a" * 64, settings=settings
    )
    assert result["storage_backend"] == "local"
    assert result["durable_storage"] is False
    assert result["source_file_path"].endswith("user-123/" + "a" * 64 + ".pdf")
    assert Path(result["source_file_path"]).read_bytes() == b"%PDF-test"


def test_s3_storage_uses_private_owner_scoped_object_and_no_public_acl(monkeypatch) -> None:
    captured = {}
    class FakeS3:
        def put_object(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(document_storage.boto3, "client", lambda *args, **kwargs: FakeS3())
    settings = SimpleNamespace(
        document_storage_backend="s3",
        object_storage_bucket="private-chronicle-bucket",
        object_storage_endpoint_url="https://objects.example.test",
        object_storage_region="auto",
        object_storage_access_key_id=_secret("test-access-key"),
        object_storage_secret_access_key=_secret("test-secret-key"),
    )
    result = document_storage.store_uploaded_pdf(
        b"%PDF-test", owner_id="user-123", sha256_hex="b" * 64, settings=settings
    )
    assert result["storage_backend"] == "s3"
    assert result["durable_storage"] is True
    assert result["source_file_path"] == "s3://private-chronicle-bucket/users/user-123/" + "b" * 64 + ".pdf"
    assert captured["Bucket"] == "private-chronicle-bucket"
    assert captured["Key"] == "users/user-123/" + "b" * 64 + ".pdf"
    assert captured["Body"] == b"%PDF-test"
    assert captured["Metadata"]["sha256"] == "b" * 64
    assert "ACL" not in captured


def test_s3_storage_fails_closed_when_credentials_missing() -> None:
    settings = SimpleNamespace(
        document_storage_backend="s3",
        object_storage_bucket="private-chronicle-bucket",
        object_storage_endpoint_url="",
        object_storage_region="us-east-1",
        object_storage_access_key_id=None,
        object_storage_secret_access_key=None,
    )
    with pytest.raises(document_storage.DocumentStorageError, match="credentials are not configured"):
        document_storage.store_uploaded_pdf(
            b"%PDF-test", owner_id="user-123", sha256_hex="c" * 64, settings=settings
        )


def test_unknown_storage_backend_is_rejected() -> None:
    settings = SimpleNamespace(document_storage_backend="public-url")
    with pytest.raises(document_storage.DocumentStorageError, match="must be either"):
        document_storage.store_uploaded_pdf(
            b"%PDF-test", owner_id="user-123", sha256_hex="d" * 64, settings=settings
        )



def test_pdf_upload_route_records_s3_durability_in_response_and_metadata(monkeypatch, client) -> None:
    captured = {}
    class FakeS3:
        def put_object(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(document_storage.boto3, "client", lambda *args, **kwargs: FakeS3())
    monkeypatch.setattr(documents, "settings", SimpleNamespace(
        max_upload_mb=5,
        max_pdf_pages=300,
        enable_pdf_ocr=False,
        pdf_ocr_max_pages=3,
        pdf_ocr_dpi=100,
        pdf_ocr_min_text_chars=20,
        pdf_ocr_language="eng",
        document_storage_backend="s3",
        object_storage_bucket="private-chronicle-bucket",
        object_storage_endpoint_url="https://objects.example.test",
        object_storage_region="auto",
        object_storage_access_key_id=_secret("test-access-key"),
        object_storage_secret_access_key=_secret("test-secret-key"),
    ))

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "A small source PDF whose original bytes should be stored privately.")
    data = pdf.tobytes()
    pdf.close()

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("source.pdf", data, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["storage_backend"] == "s3"
    assert payload["durable_storage"] is True
    assert "private object storage" in payload["note"]
    assert captured["ContentType"] == "application/pdf"
    assert "ACL" not in captured

    with TestingSessionLocal() as db:
        paper = db.get(Paper, payload["paper_id"])
        version = db.get(PaperVersion, payload["paper_version_id"])
        assert paper is not None
        assert version is not None
        assert paper.source_file_path.startswith("s3://private-chronicle-bucket/users/")
        assert version.metadata_snapshot["storage_backend"] == "s3"
        assert version.metadata_snapshot["durable_storage"] is True
