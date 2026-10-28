from pathlib import Path
from types import SimpleNamespace
import sys

from app.services.private_object_storage import store_original_pdf


def test_local_pdf_storage_uses_generated_owner_scoped_name_and_private_mode(tmp_path) -> None:
    settings = SimpleNamespace(
        object_storage_endpoint_url="",
        object_storage_bucket="",
        object_storage_access_key_id=None,
        object_storage_secret_access_key=None,
        upload_dir=str(tmp_path),
        environment="development",
    )
    result = store_original_pdf(
        b"%PDF-test",
        owner_id="user-id",
        sha256="a" * 64,
        settings=settings,
    )

    path = Path(result["reference"])
    assert path == tmp_path / "user-id" / (("a" * 64) + ".pdf")
    assert path.read_bytes() == b"%PDF-test"
    assert path.stat().st_mode & 0o777 == 0o600
    assert result["backend"] == "filesystem"
    assert result["durable"] is True


def test_serverless_filesystem_fallback_is_reported_as_non_durable(tmp_path) -> None:
    settings = SimpleNamespace(
        object_storage_endpoint_url="",
        object_storage_bucket="",
        object_storage_access_key_id=None,
        object_storage_secret_access_key=None,
        upload_dir=str(tmp_path),
        environment="production",
    )
    result = store_original_pdf(
        b"%PDF-test",
        owner_id="user-id",
        sha256="b" * 64,
        settings=settings,
    )
    assert result["backend"] == "filesystem"
    assert result["durable"] is False


def test_s3_storage_uses_private_object_key_without_public_acl(monkeypatch) -> None:
    calls = {}

    class FakeClient:
        def put_object(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda *args, **kwargs: FakeClient()))
    settings = SimpleNamespace(
        object_storage_endpoint_url="https://objects.example.test",
        object_storage_bucket="private-pdfs",
        object_storage_access_key_id="access-key",
        object_storage_secret_access_key="secret-key",
        object_storage_region="auto",
        object_storage_prefix="chronicle-private",
        upload_dir="/tmp/unused",
        environment="production",
    )

    result = store_original_pdf(
        b"%PDF-test",
        owner_id="owner-123",
        sha256="c" * 64,
        settings=settings,
    )

    assert result["reference"] == f"s3://private-pdfs/chronicle-private/owner-123/{'c' * 64}.pdf"
    assert result["durable"] is True
    assert calls["Bucket"] == "private-pdfs"
    assert calls["Key"].startswith("chronicle-private/owner-123/")
    assert calls["ContentType"] == "application/pdf"
    assert calls["CacheControl"] == "private, no-store"
    assert "ACL" not in calls


def test_partial_s3_configuration_fails_closed() -> None:
    settings = SimpleNamespace(
        object_storage_endpoint_url="https://objects.example.test",
        object_storage_bucket="private-pdfs",
        object_storage_access_key_id=None,
        object_storage_secret_access_key=None,
        upload_dir="uploads",
        environment="production",
    )
    try:
        store_original_pdf(b"%PDF-test", owner_id="owner", sha256="d" * 64, settings=settings)
    except ValueError as exc:
        assert "partially configured" in str(exc)
    else:
        raise AssertionError("Partially configured private object storage should fail closed.")


def test_serverless_env_overrides_development_default_durability(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    settings = SimpleNamespace(
        object_storage_endpoint_url="",
        object_storage_bucket="",
        object_storage_access_key_id=None,
        object_storage_secret_access_key=None,
        upload_dir=str(tmp_path),
        environment="development",
    )
    result = store_original_pdf(
        b"%PDF-test",
        owner_id="user-id",
        sha256="e" * 64,
        settings=settings,
    )
    assert result["backend"] == "filesystem"
    assert result["durable"] is False
