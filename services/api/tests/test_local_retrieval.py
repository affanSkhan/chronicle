from app.services.local_retrieval import rank_passages


def test_bm25_ranks_passages_with_matching_research_terms_first() -> None:
    passages = [
        {"id": "p1", "text": "The paper discusses unrelated image compression techniques."},
        {"id": "p2", "text": "Provenance-aware research workflow tracks citation provenance and evidence lineage."},
        {"id": "p3", "text": "A general introduction to research methods."},
    ]
    ranked = rank_passages("citation provenance evidence lineage", passages, limit=2)
    assert ranked[0]["id"] == "p2"
    assert ranked[0]["retrieval_method"] == "bm25"
    assert ranked[0]["retrieval_score"] > ranked[1]["retrieval_score"]


def test_bm25_is_stable_when_no_query_terms_match() -> None:
    passages = [
        {"id": "first", "text": "No lexical overlap here."},
        {"id": "second", "text": "Another document about a different domain."},
    ]
    ranked = rank_passages("qzxwv-unseen-term", passages, limit=2)
    assert [item["id"] for item in ranked] == ["first", "second"]
    assert all(item["retrieval_score"] == 0 for item in ranked)


def test_bm25_bounds_results_and_handles_empty_inputs() -> None:
    passages = [{"id": str(index), "text": f"evidence source {index}"} for index in range(12)]
    assert len(rank_passages("evidence", passages, limit=4)) == 4
    assert rank_passages("evidence", passages, limit=0) == []
    assert [item["id"] for item in rank_passages("", passages, limit=3)] == ["0", "1", "2"]
