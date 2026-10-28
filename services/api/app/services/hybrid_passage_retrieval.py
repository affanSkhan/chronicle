"""Optional hybrid BM25 + dense-vector passage ranking.

The lexical retriever is always available. When a Hugging Face Inference Providers
token is configured, a bounded lexical shortlist is reranked with dense embeddings,
then combined with reciprocal rank fusion (RRF). Inference failure falls back to
BM25 and is recorded in report metadata; the workflow never marks a source absent
or an item unsupported merely because the optional embedding service failed.
"""
from __future__ import annotations

import asyncio
import math
from typing import Any

import httpx

from app.services.local_passage_retrieval import rank_passages_bm25

_DEFAULT_BASE = "https://router.huggingface.co/hf-inference/models"
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_DOCUMENT_PREFIX = "Represent this passage for retrieval: "


def _unit_vector(values: list[Any]) -> list[float]:
    vector = [float(item) for item in values]
    if not vector or any(not math.isfinite(item) for item in vector):
        raise ValueError("Embedding response contains an empty or invalid vector.")
    magnitude = math.sqrt(sum(item * item for item in vector))
    if magnitude <= 0:
        raise ValueError("Embedding response contains a zero vector.")
    return [item / magnitude for item in vector]


def _mean_pool(rows: list[Any]) -> list[float]:
    vectors = [[float(value) for value in row] for row in rows if isinstance(row, list) and row]
    if not vectors:
        raise ValueError("Embedding response contains no token vectors.")
    dimension = len(vectors[0])
    if any(len(row) != dimension for row in vectors):
        raise ValueError("Embedding response contains inconsistent vector dimensions.")
    return [sum(row[column] for row in vectors) / len(vectors) for column in range(dimension)]


def _coerce_embedding_matrix(payload: Any, expected_count: int) -> list[list[float]]:
    """Accept sentence vectors and token-level vectors returned by feature-extraction models."""
    if not isinstance(payload, list):
        raise ValueError("Embedding provider returned an unexpected response shape.")
    if expected_count == 1 and payload and all(isinstance(value, (int, float)) for value in payload):
        payload = [payload]
    if len(payload) != expected_count:
        raise ValueError("Embedding provider returned a different number of vectors than requested.")

    matrix: list[list[float]] = []
    expected_dimension: int | None = None
    for item in payload:
        if isinstance(item, list) and item and all(isinstance(value, (int, float)) for value in item):
            vector = _unit_vector(item)
        elif isinstance(item, list):
            vector = _unit_vector(_mean_pool(item))
        else:
            raise ValueError("Embedding provider returned an invalid vector.")
        if expected_dimension is None:
            expected_dimension = len(vector)
        elif len(vector) != expected_dimension:
            raise ValueError("Embedding provider returned inconsistent embedding dimensions.")
        matrix.append(vector)
    return matrix


async def embed_texts_huggingface(
    texts: list[str],
    *,
    token: str,
    model: str = "BAAI/bge-small-en-v1.5",
    api_base: str = _DEFAULT_BASE,
) -> list[list[float]]:
    """Embed a bounded batch using the official Hugging Face feature-extraction API."""
    if not texts:
        return []
    if len(texts) > 48:
        raise ValueError("Embedding batch exceeds Chronicle's 48-text safety limit.")
    bounded = [str(text or "")[:1800] for text in texts]
    endpoint = f"{api_base.rstrip('/')}/{model.strip('/')}"
    headers = {"Authorization": f"Bearer {token.strip()}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), headers=headers) as client:
        response = await client.post(
            endpoint,
            json={"inputs": bounded, "normalize": True, "truncate": True},
        )
        response.raise_for_status()
        payload = response.json()
    return _coerce_embedding_matrix(payload, len(bounded))


async def rank_passages_hybrid(
    query: str,
    passages: list[dict[str, Any]],
    *,
    top_k: int = 8,
    embedding_token: str | None = None,
    embedding_model: str = "BAAI/bge-small-en-v1.5",
    embedding_api_base: str = _DEFAULT_BASE,
    lexical_shortlist: int = 32,
    extra_source_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rank passages with BM25 and optionally dense similarity + reciprocal rank fusion."""
    lexical = rank_passages_bm25(query, passages, top_k=len(passages))
    if not lexical or top_k <= 0:
        return [], {
            "method": "bm25_lexical",
            "semantic_status": "not_needed",
            "candidate_count": len(passages),
            "selected_count": 0,
        }
    if not embedding_token:
        return lexical[:top_k], {
            "method": "bm25_lexical",
            "semantic_status": "not_configured",
            "candidate_count": len(passages),
            "lexical_shortlist_count": min(len(lexical), max(1, lexical_shortlist)),
            "selected_count": min(top_k, len(lexical)),
        }

    shortlist_limit = max(1, min(int(lexical_shortlist), 40))
    shortlist = lexical[:shortlist_limit]
    shortlist_ids = {str(item.get("id") or "") for item in shortlist}
    # Preserve the best lexical candidate from each explicitly attached PDF so
    # hybrid reranking cannot accidentally omit an attached source entirely.
    reserved: list[dict[str, Any]] = []
    required_source_ids = {str(item) for item in (extra_source_ids or [])}
    for item in lexical:
        paper_id = str(item.get("paper_id") or "")
        if paper_id in required_source_ids and paper_id not in {str(p.get("paper_id") or "") for p in reserved}:
            if str(item.get("id") or "") not in shortlist_ids:
                reserved.append(item)
    shortlist.extend(reserved[:5])
    shortlist = shortlist[:48]

    texts = [
        _QUERY_PREFIX + query[:1200],
        *[
            _DOCUMENT_PREFIX
            + str(item.get("paper_title") or "")
            + (" · " + str(item.get("section_title")) if item.get("section_title") else "")
            + "\n"
            + str(item.get("text") or "")[:1400]
            for item in shortlist
        ],
    ]
    try:
        vectors = await embed_texts_huggingface(
            texts,
            token=embedding_token,
            model=embedding_model,
            api_base=embedding_api_base,
        )
        query_vector = vectors[0]
        semantic_scores = {
            str(item.get("id") or ""): sum(a * b for a, b in zip(query_vector, vectors[index + 1]))
            for index, item in enumerate(shortlist)
        }
        semantic_order = sorted(
            shortlist,
            key=lambda item: (-semantic_scores.get(str(item.get("id") or ""), -1.0), str(item.get("id") or "")),
        )
        semantic_ranks = {str(item.get("id") or ""): rank for rank, item in enumerate(semantic_order, start=1)}
        lexical_ranks = {str(item.get("id") or ""): rank for rank, item in enumerate(lexical, start=1)}
        rrf_scores: dict[str, float] = {}
        for item in lexical:
            item_id = str(item.get("id") or "")
            score = 1.0 / (60 + lexical_ranks[item_id])
            if item_id in semantic_ranks:
                score += 1.0 / (60 + semantic_ranks[item_id])
            rrf_scores[item_id] = score
        hybrid = [
            {
                **item,
                "retrieval_method": "bm25_dense_rrf" if str(item.get("id") or "") in semantic_ranks else "bm25_rrf_tail",
                "bm25_rank": lexical_ranks.get(str(item.get("id") or "")),
                "semantic_rank": semantic_ranks.get(str(item.get("id") or "")),
                "semantic_score": round(semantic_scores[str(item.get("id") or "")], 8) if str(item.get("id") or "") in semantic_scores else None,
                "retrieval_score": round(rrf_scores.get(str(item.get("id") or ""), 0.0), 8),
            }
            for item in lexical
        ]
        hybrid.sort(
            key=lambda item: (
                -(item.get("retrieval_score") or 0.0),
                item.get("bm25_rank") or 10**9,
                str(item.get("id") or ""),
            )
        )
        return hybrid[:top_k], {
            "method": "bm25_dense_reciprocal_rank_fusion",
            "semantic_status": "completed",
            "embedding_provider": "huggingface_inference_providers",
            "embedding_model": embedding_model,
            "rank_constant": 60,
            "candidate_count": len(passages),
            "lexical_shortlist_count": len(shortlist),
            "selected_count": min(top_k, len(hybrid)),
            "note": "RRF and embedding similarities are retrieval signals, not calibrated evidence confidence.",
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        # Never allow an optional embedding provider outage to fail an otherwise
        # available lexical retrieval run. The reason is a bounded class label only.
        return lexical[:top_k], {
            "method": "bm25_lexical_fallback",
            "semantic_status": "unavailable",
            "embedding_model": embedding_model,
            "candidate_count": len(passages),
            "lexical_shortlist_count": len(shortlist),
            "selected_count": min(top_k, len(lexical)),
            "note": "Dense retrieval was unavailable or returned invalid output; BM25 was used instead.",
        }
