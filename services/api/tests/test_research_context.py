from app.services.research_context import rank_passages_bm25, select_research_context


def test_bm25_ranks_query_relevant_passage_first() -> None:
    passages = [
        {"id": "p1", "text": "A general introduction to research workflows."},
        {"id": "p2", "text": "Temporal source changes and evidence impact propagation use source-event records."},
        {"id": "p3", "text": "A recipe for simple bread and soup."},
    ]
    ranked = rank_passages_bm25("source changes evidence impact propagation", passages)
    assert ranked[0]["id"] == "p2"
    assert ranked[0]["retrieval_method"] == "bm25_lexical"
    assert ranked[0]["retrieval_score"] > 0


def test_context_window_reserves_pdf_passages_and_reports_limits() -> None:
    abstracts = [
        {"id": f"a{i}", "text": f"Research on temporal evidence source event impact {i}"}
        for i in range(10)
    ]
    pdfs = [
        {"id": "d1p1", "paper_id": "d1", "extraction_method": "pymupdf", "text": "The cohort used the same dataset for temporal impact assessment."},
        {"id": "d1p2", "paper_id": "d1", "extraction_method": "pymupdf", "text": "The study describes an unrelated laboratory assay."},
        {"id": "d2p1", "paper_id": "d2", "extraction_method": "pymupdf", "text": "Source update events require reviewing downstream evidence."},
    ]
    selected, meta = select_research_context(
        "source update events and temporal evidence impact",
        abstracts,
        pdfs,
        max_total=6,
        max_document_passages=3,
    )
    assert len(selected) <= 6
    assert {"d1p1", "d2p1"}.issubset({item["id"] for item in selected})
    assert meta["selected_uploaded_pdf_passages"] >= 2
    assert meta["strategy"] == "bm25_context_ranking_with_source_diversity"
    assert all("retrieval_score" in item for item in selected)


def test_context_selector_handles_empty_sources() -> None:
    selected, meta = select_research_context("a research question", [], [])
    assert selected == []
    assert meta["candidate_scholarly_passages"] == 0
    assert meta["candidate_uploaded_pdf_passages"] == 0



def test_embedding_reranker_can_promote_semantically_relevant_passage(monkeypatch) -> None:
    import asyncio

    from app.services import research_context

    async def fake_request_embeddings(question, passages, api_key, api_base, model):
        # The first returned vector is the query vector. The second passage is
        # semantically similar despite having no exact query-term overlap.
        return [[1.0, 0.0]] + [
            ([1.0, 0.0] if item["id"] == "pdf-semantic" else [0.0, 1.0])
            for item in passages
        ]

    monkeypatch.setattr(research_context, "_request_embeddings", fake_request_embeddings)
    scholarly = [
        {"id": "abstract-lexical", "text": "source update temporal evidence passage"},
        {"id": "abstract-other", "text": "unrelated cooking and gardening"},
    ]
    pdfs = [
        {"id": "pdf-semantic", "paper_id": "doc-1", "extraction_method": "pymupdf",
         "text": "The correction notification forces an appraisal of conclusions that depend on earlier material."},
    ]
    selected, metadata = asyncio.run(research_context.select_research_context_hybrid(
        "source update temporal evidence",
        scholarly,
        pdfs,
        embedding_api_key="test-key",
        embedding_api_base="https://embedding.example/v1",
        embedding_model="test-embedding",
    ))
    assert metadata["embedding_enabled"] is True
    assert metadata["strategy"] == "bm25_embedding_reciprocal_rank_fusion"
    assert selected[0]["id"] == "pdf-semantic"
    assert selected[0]["retrieval_method"] == "bm25_embedding_rrf"


def test_embedding_provider_failure_falls_back_to_bm25(monkeypatch) -> None:
    import asyncio

    from app.services import research_context

    async def failed_embeddings(*args, **kwargs):
        raise TimeoutError("mock provider timeout")

    monkeypatch.setattr(research_context, "_request_embeddings", failed_embeddings)
    selected, metadata = asyncio.run(research_context.select_research_context_hybrid(
        "temporal evidence review",
        [{"id": "a1", "text": "temporal evidence review and provenance"}],
        [{"id": "p1", "paper_id": "d1", "extraction_method": "pymupdf",
          "text": "temporal evidence review on a source update"}],
        embedding_api_key="test-key",
        embedding_api_base="https://embedding.example/v1",
        embedding_model="test-embedding",
    ))
    assert selected
    assert metadata["embedding_enabled"] is True
    assert metadata["embedding_fallback"] == "TimeoutError"
    assert metadata["strategy"] == "bm25_context_ranking_with_source_diversity"
