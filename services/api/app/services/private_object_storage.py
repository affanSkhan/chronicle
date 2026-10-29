"""Private original-PDF storage with an S3-compatible durable backend.

Passage text is stored in Chronicle's relational database. Original PDF bytes can be
stored in a private S3-compatible bucket (AWS S3, Cloudflare R2, or compatible service).
A local filesystem fallback is retained for development. Production/serverless deployments
without a configured private object store use a nullable database binary column instead.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _secret_text(value: Any) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    raw = getter() if callable(getter) else value
    return str(raw or "").strip()


def store_original_pdf(
    data: bytes,
    *,
    owner_id: str,
    sha256: str,
    settings: Any,
) -> dict[str, Any]:
    """Store one private PDF; never make an object public or use the client filename."""
    endpoint = str(getattr(settings, "object_storage_endpoint_url", "") or "").strip()
    bucket = str(getattr(settings, "object_storage_bucket", "") or "").strip()
    access_key = _secret_text(getattr(settings, "object_storage_access_key_id", None))
    secret_key = _secret_text(getattr(settings, "object_storage_secret_access_key", None))
    region = str(getattr(settings, "object_storage_region", "auto") or "auto").strip()
    prefix = str(getattr(settings, "object_storage_prefix", "chronicle-private") or "chronicle-private").strip("/")

    configured_values = [endpoint, bucket, access_key, secret_key]
    if any(configured_values) and not all(configured_values):
        raise ValueError(
            "Private object storage is only partially configured. Set the endpoint, bucket, access key, and secret key together."
        )

    if all(configured_values):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("S3-compatible upload storage requires boto3 to be installed.") from exc

        key = f"{prefix}/{owner_id}/{sha256}.pdf"
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType="application/pdf",
            ContentDisposition="attachment",
            CacheControl="private, no-store",
            Metadata={"sha256": sha256, "owner-id": owner_id},
        )
        # Keep only a storage reference in the Paper row; secrets never enter metadata.
        return {
            "reference": f"s3://{bucket}/{key}",
            "backend": "s3",
            "durable": True,
            "object_key": key,
        }

    # Do not put production uploads on an ephemeral serverless filesystem. When a
    # private object bucket is not configured, persist the bytes on PaperVersion in
    # PostgreSQL; the upload handler applies a conservative 3 MB cap to this path.
    environment = str(getattr(settings, "environment", "development")).strip().lower()
    serverless_runtime = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
    if environment in {"production", "prod"} or serverless_runtime:
        return {
            "reference": f"dbpdf://{owner_id}/{sha256}",
            "backend": "database",
            "durable": True,
            "object_key": None,
        }

    # Local-only fallback for developer environments.
    upload_dir = Path(str(getattr(settings, "upload_dir", "uploads"))) / owner_id
    upload_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = upload_dir / f"{sha256}.pdf"
    if not destination.exists():
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(destination, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
        except Exception:
            try:
                destination.unlink(missing_ok=True)
            finally:
                raise
    else:
        os.chmod(destination, 0o600)
    durable = environment in {"development", "dev", "local", "test"} and not serverless_runtime
    return {
        "reference": str(destination),
        "backend": "filesystem",
        "durable": durable,
        "object_key": None,
    }


def delete_original_pdf(reference: str | None, *, owner_id: str, settings: Any) -> dict[str, Any]:
    """Delete an owner's original PDF, rejecting references outside their storage namespace."""
    if not reference:
        return {"deleted": False, "backend": "none"}

    if reference.startswith("dbpdf://"):
        # The owning PaperVersion row holds the bytes; its cascading row delete
        # removes the binary when the database transaction commits.
        expected = f"dbpdf://{owner_id}/"
        if not reference.startswith(expected) or not reference[len(expected):].isalnum():
            raise ValueError("The stored PDF reference is outside this account's database namespace.")
        return {"deleted": True, "backend": "database"}

    if reference.startswith("s3://"):
        from urllib.parse import urlparse

        parsed = urlparse(reference)
        endpoint = str(getattr(settings, "object_storage_endpoint_url", "") or "").strip()
        bucket = str(getattr(settings, "object_storage_bucket", "") or "").strip()
        access_key = _secret_text(getattr(settings, "object_storage_access_key_id", None))
        secret_key = _secret_text(getattr(settings, "object_storage_secret_access_key", None))
        region = str(getattr(settings, "object_storage_region", "auto") or "auto").strip()
        prefix = str(getattr(settings, "object_storage_prefix", "chronicle-private") or "chronicle-private").strip("/")
        if not all([endpoint, bucket, access_key, secret_key]):
            raise ValueError("The private object-storage configuration is required to delete this PDF's original bytes.")
        key = parsed.path.lstrip("/")
        expected_prefix = f"{prefix}/{owner_id}/"
        if parsed.netloc != bucket or not key.startswith(expected_prefix) or not key.endswith(".pdf"):
            raise ValueError("The stored PDF reference is outside this account's private storage namespace.")
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        client.delete_object(Bucket=bucket, Key=key)
        return {"deleted": True, "backend": "s3"}

    root = (Path(str(getattr(settings, "upload_dir", "uploads"))) / owner_id).resolve()
    candidate = Path(reference).resolve()
    if candidate != root and not candidate.is_relative_to(root):
        raise ValueError("The stored PDF reference is outside this account's local storage namespace.")
    candidate.unlink(missing_ok=True)
    return {"deleted": True, "backend": "filesystem"}
