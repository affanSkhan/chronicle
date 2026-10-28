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
