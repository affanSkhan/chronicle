from app.services.academic_search import (
    _clean_markup, _crossref_item, _openalex_abstract, _semantic_scholar_item,
    _DuckDuckGoResultsParser, _public_web_result_url,
)


def test_crossref_parser_normalizes_metadata() -> None:
    paper = _crossref_item({
        "DOI": "10.1234/example",
        "title": ["A Test Paper"],
        "author": [{"given": "Ada", "family": "Lovelace"}],
        "issued": {"date-parts": [[2024, 4, 1]]},
        "abstract": "<jats:p>Evidence <b>graphs</b> in research.</jats:p>",
        "publisher": "Example Press",
        "URL": "https://doi.org/10.1234/example",
    })
    assert paper is not None
    assert paper.title == "A Test Paper"
    assert paper.authors == ["Ada Lovelace"]
    assert paper.publication_year == 2024
    assert "Evidence graphs in research." in (paper.abstract or "")


def test_openalex_inverted_index_abstract_restores_order() -> None:
    assert _openalex_abstract({"Research": [0], "evidence": [1], "graph": [2]}) == "Research evidence graph"


def test_html_cleanup() -> None:
    assert _clean_markup("<p>A &amp; B</p>") == "A & B"


def test_semantic_scholar_parser_normalizes_external_ids_and_authors() -> None:
    paper = _semantic_scholar_item({
        "paperId": "s2-paper-id",
        "title": "A Scientific Evidence Graph",
        "abstract": "<p>Graph-based evidence tracking.</p>",
        "authors": [{"name": "Ada Lovelace"}, {"name": "Alan Turing"}],
        "year": 2025,
        "externalIds": {"DOI": "10.1234/chronicle"},
        "venue": "Example Journal",
        "url": "https://www.semanticscholar.org/paper/s2-paper-id",
    })
    assert paper is not None
    assert paper.provider == "semantic_scholar"
    assert paper.external_id == "s2-paper-id"
    assert paper.doi == "10.1234/chronicle"
    assert paper.authors == ["Ada Lovelace", "Alan Turing"]
    assert paper.publication_year == 2025
    assert paper.abstract == "Graph-based evidence tracking."


def test_web_result_parser_and_url_unwrapper_reject_non_http_targets() -> None:
    document = """
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fpaper">Example <b>paper</b></a>
      <a class="result__snippet">A snippet with <b>study context</b>.</a>
    </div>
    <div class="result">
      <a class="result__a" href="javascript:alert(1)">Unsafe result</a>
    </div>
    """
    parser = _DuckDuckGoResultsParser()
    parser.feed(document)
    assert len(parser.results) == 2
    assert parser.results[0]["title"] == "Example paper"
    assert parser.results[0]["snippet"] == "A snippet with study context."
    assert _public_web_result_url(parser.results[0]["href"]) == "https://example.org/paper"
    assert _public_web_result_url(parser.results[1]["href"]) is None
