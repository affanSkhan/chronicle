"""Background research runner.

The first live pipeline performs scholarly metadata discovery and persists
abstract-level passages. It deliberately does not call an abstract a verified
scientific claim; optional structured claim extraction is added as a separate
provider-backed stage.
"""
from datetime import datetime, timezone
import hashlib
import re

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import Paper, PaperVersion, Passage, ReportVersion, ResearchRun
from app.services.academic_search import search_papers


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.strip().rstrip(".") or None


def _markdown_report(question: str, papers: list[dict], provider_errors: dict[str, str], created_at: str) -> str:
    lines = [
        "# Academic Discovery Snapshot",
        "",
        f"**Research question:** {question}",
        f"**Generated:** {created_at}",
        "**Workflow:** Crossref/OpenAlex metadata retrieval with abstract passage persistence.",
        "",
        "## Important interpretation note",
        "",
        "This is a bibliographic discovery snapshot, not a completed systematic review. Abstracts and metadata have been retrieved, but claims have not automatically been verified against full-text studies. Any optional model-generated claim is labelled as unreviewed and must be checked by a researcher.",
        "",
        "## Retrieved literature",
        "",
    ]
    if not papers:
        lines.append("No papers were returned by the configured metadata providers.")
    for index, paper in enumerate(papers, start=1):
        title = paper.get("title") or "Untitled paper"
        authors = ", ".join(paper.get("authors") or []) or "Authors unavailable"
        year = paper.get("publication_year") or "Year unavailable"
        doi = _normalize_doi(paper.get("doi"))
        url = paper.get("landing_url") or (f"https://doi.org/{doi}" if doi else None)
        lines.extend([f"### {index}. {title}", "", f"- **Authors:** {authors}", f"- **Year:** {year}", f"- **Provider:** {paper.get('source_provider', 'unknown')}"])
        if doi:
            lines.append(f"- **DOI:** [{doi}](https://doi.org/{doi})")
        elif url:
            lines.append(f"- **Source:** {url}")
        abstract = (paper.get("abstract") or "").strip()
        if abstract:
            lines.extend(["", "**Abstract**", "", "> " + abstract.replace("\n", "\n> "), ""])
        else:
            lines.extend(["", "_No abstract was available from the metadata provider._", ""])
    lines.extend(["## Search coverage and limitations", ""])
    lines.append(f"- Papers persisted in this run: {len(papers)}")
    lines.append("- Search providers: Crossref and OpenAlex.")
    if provider_errors:
        lines.append("- Provider limitations: " + ", ".join(f"{name}: {reason}" for name, reason in provider_errors.items()))
    lines.append("- Provider indexing is not exhaustive; absence from this result set is not evidence that a study does not exist.")
    lines.append("- Retrieved abstracts are source text for inspection, not an automatic verdict on the research question.")
    lines.append("- Full-text extraction, citation entailment, contextual contradiction analysis and dependency-adjusted synthesis must be completed by later workflow stages.")
    return "\n".join(lines)


async def execute_research_run(run_id: str) -> None:
    """Run a single discovery job and persist its status/report.

    Every phase opens its own synchronous DB session. The async scholarly API
    calls happen outside a transaction to avoid holding a connection while
    waiting on the network.
    """
    with SessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        if run is None:
            return
        run.status = "running"
        run.error_message = None
        run.configuration = {**(run.configuration or {}), "pipeline": "scholarly-metadata-discovery", "started_at": datetime.now(timezone.utc).isoformat()}
        question = run.question
        limit = run.max_sources
        mode = run.mode
        db.commit()

    try:
        provider_result = await search_papers(question, limit=limit, provider="all")
        result_items = provider_result.get("results", [])
        saved_papers: list[dict] = []

        with SessionLocal() as db:
            run = db.get(ResearchRun, run_id)
            if run is None:
                return

            for item in result_items:
                doi = _normalize_doi(item.get("doi"))
                paper = None
                if doi:
                    paper = db.scalar(select(Paper).where(func.lower(Paper.doi) == doi.lower()))
                if paper is None and item.get("external_id"):
                    paper = db.scalar(select(Paper).where(
                        Paper.source_provider == item.get("provider", "unknown"),
                        Paper.external_id == item.get("external_id"),
                    ))

                if paper is None:
                    paper = Paper(
                        doi=doi,
                        title=item.get("title") or "Untitled paper",
                        authors=item.get("authors") or [],
                        abstract=item.get("abstract"),
                        publication_year=item.get("publication_year"),
                        publisher=item.get("publisher"),
                        source_provider=item.get("provider") or "unknown",
                        external_id=item.get("external_id"),
                        landing_url=item.get("landing_url"),
                    )
                    db.add(paper)
                    db.flush()
                else:
                    if not paper.abstract and item.get("abstract"):
                        paper.abstract = item["abstract"]
                    if not paper.authors and item.get("authors"):
                        paper.authors = item["authors"]
                    if not paper.landing_url and item.get("landing_url"):
                        paper.landing_url = item["landing_url"]
                    if not paper.publication_year and item.get("publication_year"):
                        paper.publication_year = item["publication_year"]

                abstract = (item.get("abstract") or paper.abstract or "").strip()
                abstract_hash = hashlib.sha256(abstract.encode("utf-8")).hexdigest() if abstract else None
                version_label = f"metadata-{abstract_hash[:12] if abstract_hash else hashlib.sha256(paper.title.encode('utf-8')).hexdigest()[:12]}"
                version = db.scalar(select(PaperVersion).where(
                    PaperVersion.paper_id == paper.id,
                    PaperVersion.version_label == version_label,
                ))
                if version is None:
                    version = PaperVersion(
                        paper_id=paper.id,
                        version_label=version_label,
                        publication_status="unknown",
                        retrieved_at=datetime.now(timezone.utc),
                        status_url=item.get("landing_url"),
                        metadata_snapshot={
                            "provider": item.get("provider"),
                            "external_id": item.get("external_id"),
                            "search_query": question,
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            "content_hash": abstract_hash,
                        },
                    )
                    db.add(version)
                    db.flush()

                passage_id = None
                if abstract:
                    passage = db.scalar(select(Passage).where(
                        Passage.paper_version_id == version.id,
                        Passage.text_hash == abstract_hash,
                    ))
                    if passage is None:
                        passage = Passage(
                            paper_version_id=version.id,
                            section_title="Abstract",
                            page_number=None,
                            text=abstract,
                            char_start=0,
                            char_end=len(abstract),
                            text_hash=abstract_hash,
                            extraction_method="scholarly_metadata_abstract",
                        )
                        db.add(passage)
                        db.flush()
                    passage_id = passage.id

                saved_papers.append({
                    "paper_id": paper.id,
                    "paper_version_id": version.id,
                    "passage_id": passage_id,
                    "title": paper.title,
                    "authors": paper.authors or [],
                    "publication_year": paper.publication_year,
                    "doi": paper.doi,
                    "landing_url": paper.landing_url,
                    "abstract": abstract or None,
                    "source_provider": paper.source_provider,
                })

            generated_at = datetime.now(timezone.utc).isoformat()
            latest = db.scalar(select(ReportVersion).where(ReportVersion.run_id == run_id).order_by(ReportVersion.version_number.desc()))
            report = ReportVersion(
                run_id=run_id,
                version_number=(latest.version_number + 1) if latest else 1,
                parent_version_id=latest.id if latest else None,
                title="Academic Discovery Snapshot",
                content_markdown=_markdown_report(question, saved_papers, provider_result.get("provider_errors", {}), generated_at),
                evidence_snapshot={
                    "query": question,
                    "providers_requested": provider_result.get("providers_requested"),
                    "provider_errors": provider_result.get("provider_errors", {}),
                    "paper_ids": [paper["paper_id"] for paper in saved_papers],
                    "passage_ids": [paper["passage_id"] for paper in saved_papers if paper["passage_id"]],
                    "generated_at": generated_at,
                    "claim_verification_completed": False,
                },
                change_summary="Initial metadata discovery run.",
            )
            db.add(report)
            run.status = "completed"
            run.demo = False
            run.error_message = None
            run.configuration = {
                **(run.configuration or {}),
                "pipeline": "scholarly-metadata-discovery",
                "completed_at": generated_at,
                "paper_count": len(saved_papers),
                "passage_count": sum(1 for paper in saved_papers if paper["passage_id"]),
                "provider_errors": provider_result.get("provider_errors", {}),
                "claim_verification_completed": False,
            }
            db.commit()

    except Exception as exc:
        # Store a user-safe error; do not persist request URLs, headers, or secrets.
        with SessionLocal() as db:
            run = db.get(ResearchRun, run_id)
            if run is not None:
                run.status = "failed"
                run.demo = False
                run.error_message = "Scholarly discovery failed. Check provider availability and server logs."
                run.configuration = {
                    **(run.configuration or {}),
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "failure_type": type(exc).__name__,
                }
                db.commit()
