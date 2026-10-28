"""Bounded lexical retrieval for selected PDFs and scholarly abstract passages.

Scores are retrieval heuristics, not evidence-quality or truth probabilities. A balanced
context window keeps selected documents visible alongside provider-ranked abstracts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import re
from typing import Any

import httpx

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "was",
    "what", "when", "where", "which", "who", "why", "with", "does", "do",
}


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall((text or "").lower()) if token not in _STOPWORDS and len(token) > 1]


def rank_passages_bm25(query: str, passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank passage dictionaries using a dependency-free BM25 implementation."""
    if not passages:
        return []
    query_terms = list(dict.fromkeys(_tokens(query)))
    corpus = [_tokens(str(item.get("text") or "")) for item in passages]
    lengths = [len(tokens) for tokens in corpus]
    average_length = sum(lengths) / max(1, len(lengths))
    document_frequency: Counter[str] = Counter()
    frequencies = [Counter(tokens) for tokens in corpus]
    for tokens in corpus:
        document_frequency.update(set(tokens))

    scored: list[tuple[float, int, dict[str, Any]]] = []
    total_documents = len(passages)
    for index, passage in enumerate(passages):
        score = 0.0
        term_counts = frequencies[index]
        doc_length = lengths[index]
        for term in query_terms:
            tf = term_counts.get(term, 0)
            if not tf:
                continue
            df = document_frequency[term]
            inverse_document_frequency = math.log(1.0 + (total_documents - df + 0.5) / (df + 0.5))
            denominator = tf + 1.5 * (1.0 - 0.75 + 0.75 * doc_length / max(1.0, average_length))
            score += inverse_document_frequency * (tf * 2.5) / denominator
        item = dict(passage)
        item["retrieval_score"] = round(score, 6)
        item["retrieval_method"] = "bm25_lexical"
        scored.append((score, index, item))

    # Zero-scoring records retain stable source order; zero lexical overlap does not
    # imply irrelevance, absence of evidence, or independence from other sources.
    scored.sort(key=lambda record: (-record[0], record[1]))
    return [item for _, _, item in scored]


def select_research_context(
    question: str,
    scholarly_passages: list[dict[str, Any]],
    document_passages: list[dict[str, Any]],
    *,
    max_total: int = 8,
    max_document_passages: int = 4,
    _ranked_document_passages: list[dict[str, Any]] | None = None,
    _ranked_scholarly_passages: list[dict[str, Any]] | None = None,
    strategy: str = "bm25_context_ranking_with_source_diversity",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Choose a source-diverse window of PDF chunks and scholarly abstracts."""
    total = max(1, min(int(max_total), 12))
    doc_limit = max(0, min(int(max_document_passages), total))
    ranked_documents = _ranked_document_passages if _ranked_document_passages is not None else rank_passages_bm25(question, document_passages)
    ranked_scholarly = _ranked_scholarly_passages if _ranked_scholarly_passages is not None else rank_passages_bm25(question, scholarly_passages)

    selected_documents: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    per_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for passage in ranked_documents:
        per_paper[str(passage.get("paper_id") or "unknown")].append(passage)

    # Reserve one ranked passage per selected PDF before giving any document a
    # second chunk, so a single long PDF cannot crowd out the other selected PDFs.
    for passages in per_paper.values():
        if len(selected_documents) >= doc_limit:
            break
        if passages:
            chosen = passages[0]
            selected_documents.append(chosen)
            selected_ids.add(str(chosen.get("id") or ""))

    for passage in ranked_documents:
        if len(selected_documents) >= doc_limit:
            break
        passage_id = str(passage.get("id") or "")
        if passage_id and passage_id not in selected_ids:
            selected_documents.append(passage)
            selected_ids.add(passage_id)

    remaining = total - len(selected_documents)
    selected_scholarly = [
        item for item in ranked_scholarly
        if str(item.get("id") or "") not in selected_ids
    ][:remaining]
    selected_ids.update(str(item.get("id") or "") for item in selected_scholarly)

    # If few abstracts exist, fill the remaining budget with more PDF chunks.
    room = total - len(selected_documents) - len(selected_scholarly)
    if room > 0:
        for passage in ranked_documents:
            passage_id = str(passage.get("id") or "")
            if passage_id and passage_id not in selected_ids:
                selected_documents.append(passage)
                selected_ids.add(passage_id)
                room -= 1
                if room <= 0:
                    break

    selected = (selected_documents + selected_scholarly)[:total]
    return selected, {
        "strategy": strategy,
        "candidate_scholarly_passages": len(scholarly_passages),
        "candidate_uploaded_pdf_passages": len(document_passages),
        "selected_scholarly_passages": len(selected_scholarly),
        "selected_uploaded_pdf_passages": sum(1 for item in selected if item.get("extraction_method")),
        "selected_passage_ids": [str(item["id"]) for item in selected if item.get("id")],
        "score_interpretation": "BM25 lexical relevance heuristic; not a probability, quality score, or proof of support.",
        "limit": total,
    }



async def _request_embeddings(
    question: str,
    passages: list[dict[str, Any]],
    api_key: str,
    api_base: str,
    model: str,
) -> list[list[float]]:
    """Fetch query and candidate embeddings from a separately configured provider."""
    inputs = [question[:2000]] + [str(item.get("text") or "")[:6000] for item in passages]
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(35.0, connect=8.0),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    ) as client:
        response = await client.post(
            f"{api_base.rstrip('/')}/embeddings",
            json={"model": model, "input": inputs},
        )
        response.raise_for_status()
        payload = response.json()

    data = payload.get("data")
    if not isinstance(data, list) or len(data) != len(inputs):
        raise ValueError("The embedding provider returned an unexpected result count.")
    ordered = sorted(data, key=lambda item: int(item.get("index", -1)))
    vectors: list[list[float]] = []
    for item in ordered:
        vector = item.get("embedding")
        if not isinstance(vector, list) or not vector or any(not isinstance(value, (int, float)) for value in vector):
            raise ValueError("The embedding provider returned a malformed vector.")
        vectors.append([float(value) for value in vector])
    if len({len(vector) for vector in vectors}) != 1:
        raise ValueError("The embedding provider returned inconsistent vector dimensions.")
    return vectors


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return -1.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return dot / (left_norm * right_norm)


async def select_research_context_hybrid(
    question: str,
    scholarly_passages: list[dict[str, Any]],
    document_passages: list[dict[str, Any]],
    *,
    embedding_api_key: str = "",
    embedding_api_base: str = "",
    embedding_model: str = "",
    max_total: int = 8,
    max_document_passages: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use BM25 plus embedding reciprocal-rank fusion when explicitly configured.

    Embedding candidates are bounded to 32 records, and one top lexical chunk per
    selected document is reserved first. Provider outages degrade safely to BM25.
    """
    if not (embedding_api_key and embedding_api_base and embedding_model):
        selected, metadata = select_research_context(
            question, scholarly_passages, document_passages,
            max_total=max_total, max_document_passages=max_document_passages,
        )
        metadata["embedding_enabled"] = False
        metadata["embedding_note"] = "No dedicated embedding provider configured; BM25 lexical ranking used."
        return selected, metadata

    lexical_all = rank_passages_bm25(question, document_passages + scholarly_passages)
    ranked_document_lexical = rank_passages_bm25(question, document_passages)
    candidate_pool: list[dict[str, Any]] = []
    candidate_ids: set[str] = set()

    # Reserve one lexical candidate for every selected PDF first, then fill the
    # embedding budget by BM25 rank. This bounds privacy exposure and API cost.
    per_paper: dict[str, dict[str, Any]] = {}
    for item in ranked_document_lexical:
        per_paper.setdefault(str(item.get("paper_id") or "unknown"), item)
    for item in per_paper.values():
        item_id = str(item.get("id") or "")
        if item_id and item_id not in candidate_ids and len(candidate_pool) < 32:
            candidate_pool.append(item)
            candidate_ids.add(item_id)
    for item in lexical_all:
        item_id = str(item.get("id") or "")
        if item_id and item_id not in candidate_ids and len(candidate_pool) < 32:
            candidate_pool.append(item)
            candidate_ids.add(item_id)

    if not candidate_pool:
        selected, metadata = select_research_context(question, scholarly_passages, document_passages)
        metadata["embedding_enabled"] = True
        metadata["embedding_note"] = "No passages were available to embed."
        return selected, metadata

    try:
        vectors = await _request_embeddings(
            question, candidate_pool, embedding_api_key, embedding_api_base, embedding_model
        )
        query_vector = vectors[0]
        embedding_similarity = {
            str(item["id"]): _cosine_similarity(query_vector, vectors[index + 1])
            for index, item in enumerate(candidate_pool)
        }
        embedding_order = sorted(
            embedding_similarity,
            key=lambda passage_id: (-embedding_similarity[passage_id], passage_id),
        )
        embedding_positions = {passage_id: index + 1 for index, passage_id in enumerate(embedding_order)}
        bm25_positions = {str(item.get("id")): index + 1 for index, item in enumerate(lexical_all)}
        fused: list[dict[str, Any]] = []
        for item in lexical_all:
            passage_id = str(item.get("id") or "")
            lexical_rank = bm25_positions.get(passage_id, len(lexical_all) + 1)
            embedding_rank = embedding_positions.get(passage_id)
            rrf = 1.0 / (60 + lexical_rank)
            if embedding_rank is not None:
                rrf += 1.0 / (60 + embedding_rank)
            tagged = dict(item)
            tagged["retrieval_score"] = round(rrf, 8)
            tagged["retrieval_method"] = "bm25_embedding_rrf" if embedding_rank is not None else "bm25_lexical"
            fused.append(tagged)
        fused.sort(key=lambda item: (-float(item["retrieval_score"]), str(item.get("id") or "")))
        document_ids = {str(item.get("id") or "") for item in document_passages}
        ranked_documents = [item for item in fused if str(item.get("id") or "") in document_ids]
        ranked_scholarly = [item for item in fused if str(item.get("id") or "") not in document_ids]
        selected, metadata = select_research_context(
            question, scholarly_passages, document_passages,
            max_total=max_total, max_document_passages=max_document_passages,
            _ranked_document_passages=ranked_documents,
            _ranked_scholarly_passages=ranked_scholarly,
            strategy="bm25_embedding_reciprocal_rank_fusion",
        )
        metadata["embedding_enabled"] = True
        metadata["embedding_note"] = "BM25 and embedding rankings combined with reciprocal-rank fusion; scores remain retrieval heuristics."
        metadata["embedding_candidate_count"] = len(candidate_pool)
        return selected, metadata
    except Exception as exc:
        # Keep the run available during provider outages, but disclose the fallback.
        selected, metadata = select_research_context(
            question, scholarly_passages, document_passages,
            max_total=max_total, max_document_passages=max_document_passages,
        )
        metadata["embedding_enabled"] = True
        metadata["embedding_fallback"] = type(exc).__name__
        metadata["embedding_note"] = "Embedding request failed; the bounded context fell back to BM25 lexical ranking."
        return selected, metadata
