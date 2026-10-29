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
    async def semantic_scholar(client, query, limit):
        return []

    async def web(client, query, limit):
        return []

    monkeypatch.setattr(academic_search, "search_semantic_scholar", semantic_scholar)
    monkeypatch.setattr(academic_search, "search_web", web)

    result = asyncio.run(academic_search.search_papers("evidence graph study", limit=10, provider="all"))
    papers = result["results"]

    assert [paper["doi"] for paper in papers] == ["10.1000/a", "10.1000/c", "10.1000/b"]
    assert len(papers) == 3
    assert papers[0]["provider_rank_fusion_score"] > papers[1]["provider_rank_fusion_score"]
    assert papers[1]["provider_rank_fusion_score"] > papers[2]["provider_rank_fusion_score"]
    assert result["provider_errors"] == {}


def test_semantic_scholar_results_participate_in_provider_rank_fusion(monkeypatch) -> None:
    crossref_paper = _paper("crossref", "Shared evidence source", "10.1000/shared", 2022)
    semantic_paper = _paper("semantic_scholar", "Semantic-only result", "10.1000/semantic", 2025)
    semantic_paper = semantic_paper.model_copy(update={"provider": "semantic_scholar"})

    async def crossref(client, query, limit):
        return [crossref_paper]

    async def openalex(client, query, limit):
        return []

    async def semantic_scholar(client, query, limit):
        return [semantic_paper]

    async def web(client, query, limit):
        return []

    monkeypatch.setattr(academic_search, "search_crossref", crossref)
    monkeypatch.setattr(academic_search, "search_openalex", openalex)
    monkeypatch.setattr(academic_search, "search_semantic_scholar", semantic_scholar)
    monkeypatch.setattr(academic_search, "search_web", web)

    result = asyncio.run(academic_search.search_papers("evidence graph", limit=10, provider="all"))
    by_provider = {item["provider"]: item for item in result["results"] if item["doi"] == "10.1000/semantic"}
    assert "semantic_scholar" in by_provider
    assert by_provider["semantic_scholar"]["provider_rank_fusion_score"] > 0
