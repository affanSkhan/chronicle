from app.services.academic_search import _clean_markup, _crossref_item, _openalex_abstract


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
