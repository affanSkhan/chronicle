"""Bounded BM25 plus optional embedding reranking.

The default path is local lexical BM25 and makes no embedding API calls.
When explicitly enabled and configured, Hugging Face feature extraction reranks
the top lexical candidates using reciprocal-rank fusion. It does not create a
persistent vector index and is not broad dense-vector retrieval.
"""
from __future__ import annotations
import asyncio
import math
from typing import Any
from app.services.local_retrieval import rank_passages


def _as_python(value: Any) -> Any:
    return value.tolist() if hasattr(value, "tolist") else value


def _normalize_embedding_output(raw: Any, expected_count: int) -> list[list[float]]:
    """Accept sentence vectors or token vectors from feature-extraction models."""
    values = _as_python(raw)
    if not isinstance(values, list) or len(values) != expected_count:
        raise ValueError("Embedding provider returned an unexpected batch shape.")
    vectors: list[list[float]] = []
    for item in values:
        item = _as_python(item)
        if not isinstance(item, list) or not item:
            raise ValueError("Embedding provider returned an empty vector.")
        if all(isinstance(component, (int, float)) for component in item):
            vector = [float(component) for component in item]
        else:
            token_vectors = [_as_python(token) for token in item]
            token_vectors = [[float(component) for component in token] for token in token_vectors if isinstance(token, list) and token and all(isinstance(component, (int, float)) for component in token)]
            if not token_vectors:
                raise ValueError("Embedding provider returned an invalid vector.")
            dimension = len(token_vectors[0])
            if any(len(token) != dimension for token in token_vectors):
                raise ValueError("Embedding provider returned inconsistent dimensions.")
            vector = [sum(token[index] for token in token_vectors) / len(token_vectors) for index in range(dimension)]
        if not vector or any(not math.isfinite(component) for component in vector):
            raise ValueError("Embedding provider returned non-finite values.")
        vectors.append(vector)
    if len({len(vector) for vector in vectors}) != 1:
        raise ValueError("Embedding provider returned inconsistent vector dimensions.")
    return vectors


async def _fetch_embeddings(texts: list[str], token: str, model: str) -> list[list[float]]:
    """Call Hugging Face feature extraction off the async event loop."""
    from huggingface_hub import InferenceClient
    def invoke() -> Any:
        client = InferenceClient(provider="hf-inference", api_key=token, timeout=45)
        return client.feature_extraction(texts, model=model)
    return _normalize_embedding_output(await asyncio.to_thread(invoke), len(texts))


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


async def rank_passages_hybrid(query: str, passages: list[dict[str, Any]], limit: int = 8, *, settings: Any) -> list[dict[str, Any]]:
    """Run local BM25; optionally rerank top lexical candidates with embeddings + RRF."""
    if limit <= 0 or not passages:
        return []
    enabled = bool(getattr(settings, "enable_semantic_reranking", False))
    token_value = getattr(settings, "huggingface_api_token", None)
    token_getter = getattr(token_value, "get_secret_value", None)
    token = str(token_getter() if callable(token_getter) else token_value or "").strip()
    model = str(getattr(settings, "embedding_model", "") or "").strip()
    lexical = rank_passages(query, passages, limit=min(len(passages), max(limit * 8, 32)))
    if not enabled or not token or not model:
        return [{**item, "retrieval_method": "bm25", "semantic_rerank_enabled": False} for item in lexical[:limit]]

    candidates = lexical[:min(len(lexical), 48)]
    texts = [query] + [str(item.get("text") or "")[:1600] for item in candidates]
    try:
        embeddings = await _fetch_embeddings(texts, token, model)
        similarities = [_cosine_similarity(embeddings[0], vector) for vector in embeddings[1:]]
        semantic_order = sorted(range(len(candidates)), key=lambda index: (-similarities[index], index))
        semantic_rank = {index: rank + 1 for rank, index in enumerate(semantic_order)}
        rrf_constant = 60
        fused = []
        for index, item in enumerate(candidates):
            score = 1.0 / (rrf_constant + index + 1) + 1.0 / (rrf_constant + semantic_rank[index])
            fused.append((score, index, item, similarities[index]))
        fused.sort(key=lambda row: (-row[0], row[1]))
        return [{
            **item, "retrieval_method": "bm25_embedding_rrf",
            "retrieval_score": round(score, 8), "semantic_similarity": round(similarity, 6),
            "semantic_rerank_enabled": True,
        } for score, _, item, similarity in fused[:limit]]
    except Exception:
        # Provider/model/quota problems must not erase usable lexical retrieval.
        return [{
            **item, "retrieval_method": "bm25_fallback",
            "retrieval_fallback": "embedding_provider_unavailable",
            "semantic_rerank_enabled": False,
        } for item in lexical[:limit]]
