from app.services.local_passage_retrieval import rank_passages_bm25


def test_bm25_ranks_query_relevant_uploaded_passages_first() -> None:
    passages = [
        {"id": "p1", "paper_id": "a", "text": "A survey on operating systems and kernels."},
        {"id": "p2", "paper_id": "b", "text": "Citation provenance and evidence graphs make claims inspectable."},
        {"id": "p3", "paper_id": "c", "text": "Evidence graphs connect claims to sources and provenance records."},
    ]

    ranked = rank_passages_bm25("evidence graph provenance", passages, top_k=2)

    assert [item["id"] for item in ranked] == ["p2", "p3"]
    assert ranked[0]["retrieval_method"] == "bm25_lexical"
    assert ranked[0]["retrieval_score"] > 0
    assert all("retrieval_score" not in item for item in passages)


def test_bm25_is_deterministic_and_keeps_zero_score_fallbacks() -> None:
    passages = [
        {"id": "first", "text": "Unrelated material about geology."},
        {"id": "second", "text": "Another unrelated material about botany."},
    ]

    first = rank_passages_bm25("quantum", passages, top_k=2)
    second = rank_passages_bm25("quantum", passages, top_k=2)

    assert [item["id"] for item in first] == ["first", "second"]
    assert first == second
    assert [item["retrieval_score"] for item in first] == [0.0, 0.0]


def test_bm25_handles_empty_inputs_and_nonpositive_limits() -> None:
    assert rank_passages_bm25("query", [], top_k=5) == []
    assert rank_passages_bm25("query", [{"id": "p", "text": "some passage"}], top_k=0) == []
