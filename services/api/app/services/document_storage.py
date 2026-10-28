"""Private original-document storage adapters.

The relational database stores page-aware extracted passages separately. Local files
are marked non-durable because serverless filesystems may be ephemeral. The optional
S3-compatible backend stores objects under an owner-scoped key in a private bucket;
the application never creates public ACLs or generates public URLs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import boto3


class DocumentStorageError(RuntimeError):
    """Safe, user-presentable failure to persist original document bytes."""


def _secret(value: Any) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    return str(getter() if callable(getter) else value).strip()


def store_uploaded_pdf(
    data: bytes,
    *,
    owner_id: str,
    sha256_hex: str,
    settings: Any,
) -> dict[str, Any]:
    """Persist original PDF bytes and return storage metadata without secret details."""
    backend = str(getattr(settings, "document_storage_backend", "local") or "local").strip().lower()
    if backend == "local":
        upload_dir = Path(str(getattr(settings, "upload_dir", "uploads"))) / owner_id
        try:
            upload_dir.mkdir(parents=True, exist_ok=True)
            stored_path = upload_dir / f"{sha256_hex}.pdf"
            stored_path.write_bytes(data)
        except OSError as exc:
            raise DocumentStorageError("The uploaded PDF could not be saved to local storage.") from exc
        return {
            "source_file_path": str(stored_path),
            "storage_backend": "local",
            "durable_storage": False,
            "storage_key": None,
        }

    if backend != "s3":
        raise DocumentStorageError("DOCUMENT_STORAGE_BACKEND must be either 'local' or 's3'.")

    bucket = str(getattr(settings, "object_storage_bucket", "") or "").strip()
    access_key = _secret(getattr(settings, "object_storage_access_key_id", None))
    secret_key = _secret(getattr(settings, "object_storage_secret_access_key", None))
    endpoint = str(getattr(settings, "object_storage_endpoint_url", "") or "").strip() or None
    region = str(getattr(settings, "object_storage_region", "us-east-1") or "us-east-1").strip()
    if not bucket or not access_key or not secret_key:
        raise DocumentStorageError(
            "S3 storage is enabled but the bucket and object-storage credentials are not configured."
        )

    object_key = f"users/{owner_id}/{sha256_hex}.pdf"
    try:
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        # No public ACL is supplied. Keep the bucket private and enable default
        # server-side encryption and public-access blocking in the storage console.
        client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=data,
            ContentType="application/pdf",
            CacheControl="private, no-store",
            Metadata={"sha256": sha256_hex, "owner-id": owner_id},
        )
    except Exception as exc:
        # Never expose SDK response bodies, endpoints, credentials, or request URLs.
        raise DocumentStorageError("The original PDF could not be saved to private object storage.") from exc

    return {
        "source_file_path": f"s3://{bucket}/{object_key}",
        "storage_backend": "s3",
        "durable_storage": True,
        "storage_key": object_key,
    }
