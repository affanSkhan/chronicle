"""Deterministic BM25 retrieval over passages already stored in Chronicle.

Scores are lexical ranking signals, not calibrated confidence or evidence-support
probabilities.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were",
    "what", "when", "where", "which", "who", "why", "with", "how", "does", "do",
    "using", "use", "used", "study", "paper", "research",
}


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN.findall((text or "").lower()) if len(token) > 1 and token not in _STOP_WORDS]


def rank_passages(query: str, passages: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    """Rank passages by BM25 with stable input-order tie-breaking."""
    if limit <= 0 or not passages:
        return []
    bounded = passages[:]
    query_terms = Counter(_tokens(query))
    tokenized = [_tokens(str(item.get("text") or "")) for item in bounded]
    if not query_terms or not any(tokenized):
        return [{**item, "retrieval_method": "bm25", "retrieval_score": 0.0} for item in bounded[:limit]]

    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    count = len(tokenized)
    average_length = sum(len(tokens) for tokens in tokenized) / max(count, 1)
    k1, b = 1.5, 0.75
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for index, (item, tokens) in enumerate(zip(bounded, tokenized)):
        frequencies = Counter(tokens)
        score = 0.0
        length = len(tokens)
        for term, query_frequency in query_terms.items():
            tf = frequencies.get(term, 0)
            if not tf:
                continue
            df = document_frequency[term]
            idf = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
            norm = tf + k1 * (1.0 - b + b * length / max(average_length, 1.0))
            score += idf * (tf * (k1 + 1.0) / norm) * (1.0 + math.log(query_frequency))
        ranked.append((score, index, item))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [{**item, "retrieval_method": "bm25", "retrieval_score": round(score, 6)} for score, _, item in ranked[:limit]]
