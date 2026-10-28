"""Metadata search adapters for public scholarly APIs.

This module returns bibliographic metadata only. It does not claim that an
abstract is full-text evidence or that a retrieved paper supports a claim.
"""
import asyncio
import html
import re
from typing import Any

import httpx

from app.core.config import openalex_auth_headers
from app.schemas.evidence import PaperSearchResult

USER_AGENT = "Chronicle/0.1.0 (https://github.com/affanSkhan/chronicle)"
CROSSREF_URL = "https://api.crossref.org/works"
OPENALEX_URL = "https://api.openalex.org/works"


def _clean_markup(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text or None


def _year_from_parts(parts: Any) -> int | None:
    try:
        year = int(parts[0])
        return year if 1600 <= year <= 2200 else None
    except (TypeError, ValueError, IndexError):
        return None


def _crossref_item(item: dict[str, Any]) -> PaperSearchResult | None:
    titles = item.get("title") or []
    title = (titles[0] if titles else "").strip()
    if not title:
        return None
    authors = []
    for author in item.get("author") or []:
        name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
        if name:
            authors.append(name)
    date = item.get("published-print") or item.get("published-online") or item.get("issued") or {}
    return PaperSearchResult(
        provider="crossref",
        external_id=item.get("DOI"),
        doi=item.get("DOI"),
        title=title,
        authors=authors,
        abstract=_clean_markup(item.get("abstract")),
        publication_year=_year_from_parts((date.get("date-parts") or [[]])[0]) if date.get("date-parts") else None,
        publisher=item.get("publisher"),
        landing_url=item.get("URL"),
    )


def _openalex_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    if not inverted:
        return None
    pairs: list[tuple[int, str]] = []
    for token, positions in inverted.items():
        for position in positions:
            pairs.append((position, token))
    if not pairs:
        return None
    pairs.sort(key=lambda pair: pair[0])
    return " ".join(token for _, token in pairs)


def _openalex_item(item: dict[str, Any]) -> PaperSearchResult | None:
    title = (item.get("title") or "").strip()
    if not title:
        return None
    authors = []
    for authorship in item.get("authorships") or []:
        author = (authorship.get("author") or {}).get("display_name")
        if author:
            authors.append(author)
    ids = item.get("ids") or {}
    doi = item.get("doi") or ids.get("doi")
    if doi and doi.lower().startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]
    location = item.get("primary_location") or {}
    return PaperSearchResult(
        provider="openalex",
        external_id=item.get("id") or ids.get("openalex"),
        doi=doi,
        title=title,
        authors=authors,
        abstract=_openalex_abstract(item.get("abstract_inverted_index")),
        publication_year=item.get("publication_year"),
        publisher=(location.get("source") or {}).get("display_name"),
        landing_url=location.get("landing_page_url") or item.get("id"),
    )


async def search_crossref(client: httpx.AsyncClient, query: str, limit: int) -> list[PaperSearchResult]:
    response = await client.get(CROSSREF_URL, params={"query.bibliographic": query, "rows": limit})
    response.raise_for_status()
    items = response.json().get("message", {}).get("items", [])
    return [paper for item in items if (paper := _crossref_item(item)) is not None]


async def search_openalex(client: httpx.AsyncClient, query: str, limit: int) -> list[PaperSearchResult]:
    # Keep the key in an Authorization header and scope it only to OpenAlex.
    headers = openalex_auth_headers()
    request_args: dict[str, Any] = {"params": {"search": query, "per-page": limit}}
    if headers:
        request_args["headers"] = headers
    response = await client.get(OPENALEX_URL, **request_args)
    response.raise_for_status()
    items = response.json().get("results", [])
    return [paper for item in items if (paper := _openalex_item(item)) is not None]


async def search_papers(query: str, limit: int = 10, provider: str = "all") -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    timeout = httpx.Timeout(20.0, connect=8.0)
    results: list[PaperSearchResult] = []
    errors: dict[str, str] = {}
    rank_fusion_scores: dict[str, float] = {}

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        tasks = {}
        if provider in {"all", "crossref"}:
            tasks["crossref"] = search_crossref(client, query, limit)
        if provider in {"all", "openalex"}:
            tasks["openalex"] = search_openalex(client, query, limit)
        completed = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for name, result in zip(tasks.keys(), completed):
            if isinstance(result, Exception):
                errors[name] = "Provider request failed or was unavailable."
                continue
            # Preserve each provider's own relevance order. DOI identity is
            # normalized below, and reciprocal rank fusion combines providers.
            for rank, paper in enumerate(result, start=1):
                key = f"doi:{paper.doi.lower().strip()}" if paper.doi else f"title:{' '.join(paper.title.lower().split())}"
                rank_fusion_scores[key] = rank_fusion_scores.get(key, 0.0) + 1.0 / (60 + rank)
                results.append(paper)

    # Prefer DOI identity for deduplication; fallback to normalized title/provider.
    unique: dict[str, PaperSearchResult] = {}
    for paper in results:
        key = f"doi:{paper.doi.lower().strip()}" if paper.doi else f"title:{' '.join(paper.title.lower().split())}"
        prior = unique.get(key)
        if prior is None:
            unique[key] = paper
        else:
            merged = prior.model_copy(update={
                "abstract": prior.abstract or paper.abstract,
                "authors": prior.authors or paper.authors,
                "landing_url": prior.landing_url or paper.landing_url,
                "publisher": prior.publisher or paper.publisher,
                "publication_year": prior.publication_year or paper.publication_year,
            })
            unique[key] = merged
    # RRF combines Crossref and OpenAlex ranks without pretending their raw
    # scores are calibrated or directly comparable. Recency is only a tie-breaker.
    output_items = sorted(
        unique.items(),
        key=lambda item: (
            rank_fusion_scores.get(item[0], 0.0),
            item[1].publication_year or 0,
            bool(item[1].abstract),
            item[1].title.lower(),
        ),
        reverse=True,
    )
    output = [paper for _, paper in output_items]
    if not output and errors:
        raise httpx.HTTPError(f"All requested scholarly providers failed: {', '.join(errors.keys())}")
    return {
        "query": query,
        "providers_requested": provider,
        "results": [
            {
                **paper.model_dump(mode="json"),
                "provider_rank_fusion_score": round(rank_fusion_scores.get(
                    f"doi:{paper.doi.lower().strip()}" if paper.doi else f"title:{' '.join(paper.title.lower().split())}",
                    0.0,
                ), 8),
            }
            for paper in output[:limit]
        ],
        "provider_errors": errors,
        "note": "Metadata search only; results have not been verified as evidence for any claim.",
    }
