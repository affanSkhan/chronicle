import asyncio

from app.schemas.evidence import PaperSearchResult
from app.services import academic_search


def _paper(provider: str, title: str, doi: str, year: int) -> PaperSearchResult:
    return PaperSearchResult(
        provider=provider,
        external_id=doi,
        doi=doi,
        title=title,
        publication_year=year,
        abstract=f"Abstract for {title}.",
        landing_url=f"https://doi.org/{doi}",
    )


def test_scholarly_search_fuses_provider_ranks_and_deduplicates(monkeypatch) -> None:
    a_crossref = _paper("crossref", "Repeated evidence graph study", "10.1000/a", 2020)
    b_crossref = _paper("crossref", "A second study", "10.1000/b", 2025)
    c_crossref = _paper("crossref", "A third study", "10.1000/c", 2024)
    a_openalex = _paper("openalex", "Repeated evidence graph study", "10.1000/a", 2020)
    c_openalex = _paper("openalex", "A third study", "10.1000/c", 2024)

    async def crossref(client, query, limit):
        return [a_crossref, b_crossref, c_crossref]

    async def openalex(client, query, limit):
        return [a_openalex, c_openalex]

    monkeypatch.setattr(academic_search, "search_crossref", crossref)
    monkeypatch.setattr(academic_search, "search_openalex", openalex)

    result = asyncio.run(academic_search.search_papers("evidence graph study", limit=10, provider="all"))
    papers = result["results"]

    assert [paper["doi"] for paper in papers] == ["10.1000/a", "10.1000/c", "10.1000/b"]
    assert len(papers) == 3
    assert papers[0]["provider_rank_fusion_score"] > papers[1]["provider_rank_fusion_score"]
    assert papers[1]["provider_rank_fusion_score"] > papers[2]["provider_rank_fusion_score"]
    assert result["provider_errors"] == {}
