import asyncio
from types import SimpleNamespace

from app.services import hybrid_retrieval


def _settings(enabled=False, token=None):
    return SimpleNamespace(
        enable_semantic_reranking=enabled,
        huggingface_api_token=token,
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    )


def test_reranker_is_disabled_by_default_without_external_calls(monkeypatch):
    async def must_not_embed(*args, **kwargs):
        raise AssertionError("The default local retrieval path must not call an embedding provider.")

    monkeypatch.setattr(hybrid_retrieval, "_fetch_embeddings", must_not_embed)
    passages = [
        {"id": "p1", "text": "citation provenance evidence trace"},
        {"id": "p2", "text": "general image compression methods"},
    ]
    result = asyncio.run(hybrid_retrieval.rank_passages_hybrid("citation provenance", passages, 1, settings=_settings()))
    assert result[0]["id"] == "p1"
    assert result[0]["retrieval_method"] == "bm25"
    assert result[0]["semantic_rerank_enabled"] is False


def test_reranker_uses_embeddings_when_explicitly_enabled(monkeypatch):
    passages = [
        {"id": "p1", "text": "citation provenance evidence trace"},
        {"id": "p2", "text": "some lexically less aligned passage"},
        {"id": "p3", "text": "completely unrelated image compression"},
        {"id": "p4", "text": "another unrelated weather report"},
    ]

    async def fake_embeddings(texts, token, model):
        assert texts[0] == "citation provenance"
        assert len(texts) == len(passages) + 1
        return [[1.0, 0.0], [0.0, 1.0], [0.99, 0.01], [0.1, 0.9], [0.0, 1.0]]

    monkeypatch.setattr(hybrid_retrieval, "_fetch_embeddings", fake_embeddings)
    result = asyncio.run(hybrid_retrieval.rank_passages_hybrid(
        "citation provenance", passages, 4,
        settings=_settings(enabled=True, token="hf-test-token"),
    ))
    assert all(item["retrieval_method"] == "bm25_embedding_rrf" for item in result)
    assert all(item["semantic_rerank_enabled"] is True for item in result)
    assert all("semantic_similarity" in item for item in result)
    # The semantic nearest neighbour p2 outranks the lexically strongest p1.
    assert result[0]["id"] == "p2"


def test_reranker_falls_back_to_bm25_when_provider_fails(monkeypatch):
    async def failed_embeddings(texts, token, model):
        raise RuntimeError("provider offline")

    monkeypatch.setattr(hybrid_retrieval, "_fetch_embeddings", failed_embeddings)
    result = asyncio.run(hybrid_retrieval.rank_passages_hybrid(
        "citation provenance", [{"id": "p1", "text": "citation provenance support"}], 1,
        settings=_settings(enabled=True, token="hf-test-token"),
    ))
    assert result[0]["retrieval_method"] == "bm25_fallback"
    assert result[0]["retrieval_fallback"] == "embedding_provider_unavailable"


def test_embedding_normalization_supports_sentence_and_token_vectors():
    assert hybrid_retrieval._normalize_embedding_output([[1, 0], [0, 1]], 2) == [[1.0, 0.0], [0.0, 1.0]]
    assert hybrid_retrieval._normalize_embedding_output([[[1, 0], [0, 1]], [[2, 2], [4, 4]]], 2) == [[0.5, 0.5], [3.0, 3.0]]
