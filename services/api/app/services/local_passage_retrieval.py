"""Bounded lexical retrieval for locally stored evidence passages.

This implements BM25-style ranking for user-uploaded PDF passages without requiring
an embedding API or additional paid service. It is a lexical retrieval component,
not semantic search; callers should preserve its method/score in run metadata.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable


_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "was",
    "were", "with", "we", "our", "their", "these", "those", "into", "than",
    "then", "can", "could", "should", "would", "may", "might", "using",
}


def _tokens(value: str) -> list[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(value or "")
        if len(token) > 1 and token.lower() not in _STOPWORDS
    ]


def rank_passages_bm25(
    query: str,
    passages: Iterable[dict[str, Any]],
    *,
    top_k: int = 8,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[dict[str, Any]]:
    """Return up to top_k passage dictionaries ranked by deterministic BM25.

    Ties preserve input order. Zero-score passages are retained as a fallback so
    the caller can still offer a bounded excerpt when query vocabulary does not
    overlap the document. The input dictionaries are copied, never mutated.
    """
    candidates = list(passages)
    if top_k <= 0 or not candidates:
        return []
    tokenized = [_tokens(str(item.get("text") or "")) for item in candidates]
    query_terms = list(dict.fromkeys(_tokens(query)))
    if not query_terms:
        return [
            {**item, "retrieval_method": item.get("retrieval_method", "bm25_lexical"), "retrieval_score": 0.0}
            for item in candidates[:top_k]
        ]

    lengths = [len(doc) for doc in tokenized]
    average_length = sum(lengths) / len(lengths) if lengths else 0.0
    document_frequency: Counter[str] = Counter()
    term_frequencies = [Counter(doc) for doc in tokenized]
    for doc in tokenized:
        document_frequency.update(set(doc))

    total = len(candidates)
    ranked: list[tuple[float, int]] = []
    for index, frequencies in enumerate(term_frequencies):
        score = 0.0
        doc_length = lengths[index]
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            df = document_frequency.get(term, 0)
            inverse_frequency = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (
                1.0 - b + b * (doc_length / average_length if average_length else 0.0)
            )
            score += inverse_frequency * (frequency * (k1 + 1.0)) / denominator
        ranked.append((score, index))

    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    return [
        {
            **candidates[index],
            "retrieval_method": candidates[index].get("retrieval_method", "bm25_lexical"),
            "retrieval_score": round(score, 8),
        }
        for score, index in ranked[:top_k]
    ]
