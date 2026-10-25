"""External post-publication status signals from Crossref and OpenAlex.

Signals are a monitoring aid only. They never mutate a paper's publication
status or create source events by themselves; users must review the notice.
"""
from typing import Any
from urllib.parse import quote
import re

import httpx

from app.core.config import openalex_auth_headers


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.strip().rstrip(".") or None


async def fetch_paper_status_signals(doi_value: str) -> dict[str, Any]:
    doi = normalize_doi(doi_value)
    if not doi:
        return {
            "providers": {"crossref": "skipped_no_doi", "openalex": "skipped_no_doi"},
            "signals": [],
            "note": "No DOI was available for the selected paper.",
        }

    headers = {
        "User-Agent": "Chronicle/0.1.0 (https://github.com/affanSkhan/chronicle)",
        "Accept": "application/json",
    }
    timeout = httpx.Timeout(20.0, connect=8.0)
    providers: dict[str, str] = {}
    signals: list[dict[str, Any]] = []

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        try:
            response = await client.get(f"https://api.crossref.org/works/{quote(doi, safe='/')}")
            response.raise_for_status()
            item = response.json().get("message", {})
            providers["crossref"] = "ok"
            for update in item.get("update-to") or []:
                update_type_raw = str(update.get("type") or "metadata_change").strip().lower()
                mapped = {
                    "retraction": "retraction",
                    "correction": "correction",
                    "expression-of-concern": "expression_of_concern",
                    "expression_of_concern": "expression_of_concern",
                    "removal": "retraction",
                }.get(update_type_raw, "metadata_change")
                update_doi = normalize_doi(update.get("DOI"))
                signals.append({
                    "provider": "crossref",
                    "event_type": mapped,
                    "update_type": update_type_raw,
                    "description": str(update.get("label") or f"Crossref reports an update relationship of type '{update_type_raw}'."),
                    "source_url": f"https://doi.org/{update_doi}" if update_doi else None,
                    "verification_status": "metadata_confirmed",
                    "metadata": update,
                })
        except Exception:
            providers["crossref"] = "unavailable"

        try:
            openalex_headers = openalex_auth_headers()
            request_args: dict[str, Any] = {
                "params": {
                    "filter": f"doi:https://doi.org/{doi}",
                    "per-page": 1,
                    "select": "id,doi,title,is_retracted,updated_date",
                },
            }
            if openalex_headers:
                request_args["headers"] = openalex_headers
            response = await client.get("https://api.openalex.org/works", **request_args)
            response.raise_for_status()
            results = response.json().get("results") or []
            matched = results[0] if results else None
            providers["openalex"] = "ok" if matched else "not_found"
            if matched and matched.get("is_retracted") is True and not any(signal["event_type"] == "retraction" for signal in signals):
                signals.append({
                    "provider": "openalex",
                    "event_type": "retraction",
                    "update_type": "is_retracted",
                    "description": "OpenAlex marks this work as retracted. Confirm the underlying notice before recording a verified event.",
                    "source_url": matched.get("id"),
                    "verification_status": "metadata_confirmed",
                    "metadata": {"openalex_id": matched.get("id"), "updated_date": matched.get("updated_date")},
                })
        except Exception:
            providers["openalex"] = "unavailable"

    return {
        "providers": providers,
        "signals": signals,
        "note": "Metadata preview only. No publication status is changed and no source event is created automatically. Verify the underlying notice before recording a reviewed event.",
    }


def stable_signal_fingerprint(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return stable identity fields, excluding volatile provider payload details."""
    return sorted(
        [
            {
                "provider": str(signal.get("provider") or ""),
                "event_type": str(signal.get("event_type") or ""),
                "update_type": str(signal.get("update_type") or ""),
                "source_url": signal.get("source_url"),
            }
            for signal in signals
        ],
        key=lambda item: (item["provider"], item["event_type"], item["update_type"], item["source_url"] or ""),
    )
