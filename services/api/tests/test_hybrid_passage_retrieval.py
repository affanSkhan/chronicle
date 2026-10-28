import asyncio

import pytest

from app.services import hybrid_passage_retrieval as hybrid


def test_hybrid_retrieval_combines_dense_and_lexical_rankings(monkeypatch) -> None:
    passages = [
        {
            "id": "lexical",
            "paper_id": "pdf-1",
            "paper_title": "Vehicle safety report",
            "text": "Automobile safety crash impact and protective systems.",
            "source_kind": "uploaded_pdf",
        },
        {
            "id": "semantic",
            "paper_id": "pdf-2",
            "paper_title": "Road transport",
            "text": "A car's collision survivability is improved by restraint design.",
            "source_kind": "uploaded_pdf",
        },
        {
            "id": "irrelevant",
            "paper_id": "pdf-3",
            "paper_title": "Botany report",
            "text": "The experiment measured leaf chlorophyll in plants.",
            "source_kind": "uploaded_pdf",
        },
    ]

    async def fake_embeddings(texts: list[str], **kwargs) -> list[list[float]]:
        # Query vector is similar to the synonym-based semantic result and not
        # the exact-keyword lexical winner.
        assert len(texts) == 4
        return [
            [1.0, 0.0],
            [0.1, 0.995],
            [0.99, 0.1],
            [-0.8, 0.2],
        ]

    monkeypatch.setattr(hybrid, "embed_texts_huggingface", fake_embeddings)
    result, diagnostics = asyncio.run(hybrid.rank_passages_hybrid(
        "vehicle collision safety",
        passages,
        top_k=2,
        embedding_token="test-token",
        extra_source_ids=["pdf-1", "pdf-2"],
    ))

    assert diagnostics["method"] == "bm25_dense_reciprocal_rank_fusion"
    assert diagnostics["semantic_status"] == "completed"
    assert {item["id"] for item in result} == {"lexical", "semantic"}
    assert all(item["retrieval_method"] == "bm25_dense_rrf" for item in result)
    assert all(item["semantic_score"] is not None for item in result)


def test_hybrid_retrieval_falls_back_to_lexical_on_embedding_failure(monkeypatch) -> None:
    passages = [
        {"id": "a", "paper_id": "one", "text": "evidence graph provenance"},
        {"id": "b", "paper_id": "two", "text": "garden plant growth"},
    ]

    async def unavailable(*args, **kwargs):
        raise RuntimeError("provider secret or request payload must not be logged")

    monkeypatch.setattr(hybrid, "embed_texts_huggingface", unavailable)
    result, diagnostics = asyncio.run(hybrid.rank_passages_hybrid(
        "evidence graph provenance",
        passages,
        top_k=2,
        embedding_token="test-token",
    ))

    assert [item["id"] for item in result] == ["a", "b"]
    assert diagnostics["method"] == "bm25_lexical_fallback"
    assert diagnostics["semantic_status"] == "unavailable"
    assert "secret" not in str(diagnostics).lower()


def test_embedding_response_validation_rejects_mismatched_batches() -> None:
    with pytest.raises(ValueError):
        hybrid._coerce_embedding_matrix([[1.0, 0.0]], expected_count=2)


def test_huggingface_embedding_batch_is_bounded() -> None:
    with pytest.raises(ValueError):
        asyncio.run(hybrid.embed_texts_huggingface(
            ["text"] * 49,
            token="test-token",
        ))
