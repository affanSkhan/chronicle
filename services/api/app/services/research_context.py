"""Bounded lexical retrieval for selected PDFs and scholarly abstract passages.

Scores are retrieval heuristics, not evidence-quality or truth probabilities. A balanced
context window keeps selected documents visible alongside provider-ranked abstracts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import re
from typing import Any

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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Choose a source-diverse window of PDF chunks and scholarly abstracts."""
    total = max(1, min(int(max_total), 12))
    doc_limit = max(0, min(int(max_document_passages), total))
    ranked_documents = rank_passages_bm25(question, document_passages)
    ranked_scholarly = rank_passages_bm25(question, scholarly_passages)

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
        "strategy": "bm25_context_ranking_with_source_diversity",
        "candidate_scholarly_passages": len(scholarly_passages),
        "candidate_uploaded_pdf_passages": len(document_passages),
        "selected_scholarly_passages": len(selected_scholarly),
        "selected_uploaded_pdf_passages": sum(1 for item in selected if item.get("extraction_method")),
        "selected_passage_ids": [str(item["id"]) for item in selected if item.get("id")],
        "score_interpretation": "BM25 lexical relevance heuristic; not a probability, quality score, or proof of support.",
        "limit": total,
    }
