"""Background research runner: scholarly discovery plus optional structured extraction.

Model-generated claims remain unreviewed. Each edge is checked against the
passage IDs supplied to the model and labelled model-inferred, not verified.
"""
from datetime import datetime, timezone
import hashlib
import re

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import Claim, EvidenceRelation, Paper, PaperVersion, Passage, ReportVersion, ResearchRun
from app.services.academic_search import search_papers
from app.services.claim_extraction import extract_claims_from_passages
from app.services.evidence_synthesis import synthesize_evidence


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.strip().rstrip(".") or None


def _markdown_report(
    question: str,
    mode: str,
    papers: list[dict],
    provider_errors: dict[str, str],
    created_at: str,
    extracted_claims: list[dict],
    llm_note: str,
    synthesis: dict | None,
    synthesis_note: str,
) -> str:
    lines = [
        "# Academic Discovery Snapshot",
        "",
        f"**Research question:** {question}",
        f"**Mode:** {mode}",
        f"**Generated:** {created_at}",
        "**Workflow:** Crossref/OpenAlex metadata retrieval, abstract passage persistence, and optional structured claim extraction.",
        "",
        "## Important interpretation note",
        "",
        "This is a bibliographic discovery snapshot, not a completed systematic review. Abstracts and metadata are retrieved, but they do not replace full-text appraisal. Any model-generated claim below is unreviewed and must be checked by a researcher.",
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
        if paper.get("passage_id"):
            lines.append(f"- **Abstract passage ID:** {paper['passage_id']}")
        abstract = (paper.get("abstract") or "").strip()
        if abstract:
            lines.extend(["", "**Abstract**", "", "> " + abstract.replace("\n", "\n> "), ""])
        else:
            lines.extend(["", "_No abstract was available from the metadata provider._", ""])

    lines.extend(["## Evidence-bounded synthesis", ""])
    if not synthesis:
        lines.append("No model-generated synthesis was produced. " + synthesis_note)
    else:
        lines.append("**Draft status:** This model-assisted synthesis uses retrieved abstracts, not a complete full-text review. Every listed finding below has at least one validated passage ID; the summary remains subject to human review.")
        lines.extend(["", "### Summary", "", synthesis.get("executive_summary", "No summary supplied."), ""])
        lines.extend(["### Evidence-linked findings", ""])
        findings = synthesis.get("findings", [])
        if not findings:
            lines.append("No findings with valid source passage references were returned.")
        for index, finding in enumerate(findings, start=1):
            lines.append(f"{index}. **{finding['statement']}**")
            lines.append(f"   - Relationship assessment: {finding.get('relation_type', 'qualifies')}")
            if finding.get("context_note"):
                lines.append(f"   - Context: {finding['context_note']}")
            for passage_id in finding.get("evidence_passage_ids", []):
                paper = next((item for item in papers if item.get("passage_id") == passage_id), None)
                if paper:
                    doi = _normalize_doi(paper.get("doi"))
                    source_url = f"https://doi.org/{doi}" if doi else (paper.get("landing_url") or "")
                    title = paper.get("title") or "Source paper"
                    source_label = f"[{title}]({source_url})" if source_url else title
                    lines.append(f"   - Evidence trace: {source_label} · abstract passage ID {passage_id}")
                else:
                    lines.append(f"   - Evidence trace: abstract passage ID {passage_id}")
            lines.append("")
        disagreements = synthesis.get("disagreements", [])
        if disagreements:
            lines.extend(["### Possible disagreements and comparability", ""])
            for disagreement in disagreements:
                lines.append(f"- {disagreement['description']}")
                if disagreement.get("comparability_note"):
                    lines.append(f"  - Comparability: {disagreement['comparability_note']}")
                lines.append("  - Passage IDs: " + ", ".join(disagreement.get("evidence_passage_ids", [])))
        limitations = synthesis.get("limitations", [])
        if limitations:
            lines.extend(["", "### Limitations reported by the synthesis", ""])
            lines.extend(f"- {item}" for item in limitations)
        questions = synthesis.get("candidate_research_questions", [])
        if questions:
            lines.extend(["", "### Candidate research questions (not novelty claims)", ""])
            lines.extend(f"- {item}" for item in questions)
        lines.extend(["", "**Uncertainty:** " + synthesis.get("uncertainty_statement", "Uncertainty was not provided."), ""])
    lines.append(synthesis_note)
    lines.append("")

    lines.extend(["## Candidate claims", ""])
    if not extracted_claims:
        lines.append("No model-generated candidate claims were added. " + llm_note)
    else:
        lines.append("These are model-extracted candidates linked to abstract passages. They are not independently verified conclusions.")
        lines.append("")
        for index, claim in enumerate(extracted_claims, start=1):
            lines.append(f"{index}. **{claim['statement']}**")
            if claim.get("uncertainty_notes"):
                lines.append(f"   - Uncertainty: {claim['uncertainty_notes']}")
            for evidence in claim.get("evidence", []):
                lines.append(f"   - {evidence['relation_type']} passage {evidence['passage_id']}: {evidence['rationale']}")
            lines.append("")

    lines.extend(["## Search coverage and limitations", ""])
    lines.append(f"- Papers persisted in this run: {len(papers)}")
    lines.append("- Search providers: Crossref and OpenAlex.")
    if provider_errors:
        lines.append("- Provider limitations: " + ", ".join(f"{name}: {reason}" for name, reason in provider_errors.items()))
    lines.append("- Provider indexing is not exhaustive; absence from this result set is not evidence that a study does not exist.")
    lines.append("- Retrieved abstracts are source text for inspection, not an automatic verdict on the research question.")
    lines.append("- Claims are marked model-inferred/unreviewed; a model response is not proof of truth.")
    lines.append("- Source dependency detection, context-aware contradiction adjudication, full-text citation entailment and calibrated evidence weighting require further evaluation.")
    return "\n".join(lines)


async def execute_research_run(run_id: str) -> None:
    """Execute a discovery run and persist its status, source records and report."""
    with SessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        if run is None:
            return
        run.status = "running"
        run.error_message = None
        run.configuration = {
            **(run.configuration or {}),
            "pipeline": "scholarly-metadata-discovery",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        question = run.question
        limit = run.max_sources
        mode = run.mode
        db.commit()

    try:
        provider_result = await search_papers(question, limit=limit, provider="all")
        result_items = provider_result.get("results", [])
        saved_papers: list[dict] = []
        passages_for_extraction: list[dict] = []

        # Phase 1: persist papers, versions and abstract passages.
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
                version_source = abstract_hash if abstract_hash else hashlib.sha256(paper.title.encode("utf-8")).hexdigest()
                version_label = f"metadata-{version_source[:12]}"
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
                    passages_for_extraction.append({
                        "id": passage_id,
                        "paper_title": paper.title,
                        "doi": paper.doi,
                        "text": abstract,
                    })

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
            db.commit()

        # Phase 2: optional model-backed candidates; retrieval-only mode is valid.
        settings = get_settings()
        extracted_claims: list[dict] = []
        llm_note = "LLM extraction skipped because OPENAI_API_KEY and OPENAI_MODEL are not both configured."
        extraction_error: str | None = None
        api_key = settings.openai_api_key.get_secret_value().strip() if settings.openai_api_key else ""
        if api_key and settings.openai_model.strip() and passages_for_extraction:
            try:
                extracted_claims = await extract_claims_from_passages(
                    question=question,
                    passages=passages_for_extraction,
                    api_key=api_key,
                    api_base=settings.openai_api_base,
                    model=settings.openai_model.strip(),
                )
                llm_note = "Structured extraction completed; generated claims and evidence edges still require human review."
            except Exception as exc:
                extraction_error = type(exc).__name__
                llm_note = "LLM extraction failed; the bibliographic discovery report was completed without model-generated claims."

        synthesis_result: dict | None = None
        synthesis_note = "Model synthesis skipped because OPENAI_API_KEY and OPENAI_MODEL are not both configured."
        synthesis_error: str | None = None
        if api_key and settings.openai_model.strip() and passages_for_extraction:
            try:
                synthesis_result = await synthesize_evidence(
                    question=question,
                    passages=passages_for_extraction,
                    api_key=api_key,
                    api_base=settings.openai_api_base,
                    model=settings.openai_model.strip(),
                )
                synthesis_note = "Model synthesis completed; draft findings and candidate research questions still require human review."
            except Exception as exc:
                synthesis_error = type(exc).__name__
                synthesis_note = "Model synthesis failed; the bibliographic discovery report was completed without it."

        persisted_claims: list[dict] = []
        if extracted_claims:
            allowed_passage_ids = {str(p["id"]) for p in passages_for_extraction}
            with SessionLocal() as db:
                for proposal in extracted_claims:
                    valid_evidence = [e for e in proposal["evidence"] if e["passage_id"] in allowed_passage_ids]
                    if not valid_evidence:
                        continue
                    claim = Claim(
                        run_id=run_id,
                        statement=proposal["statement"],
                        scope=proposal.get("scope") or {},
                        assessment="unassessed",
                        review_required=True,
                        uncertainty_notes=proposal.get("uncertainty_notes"),
                    )
                    db.add(claim)
                    db.flush()
                    stored_edges = []
                    for evidence in valid_evidence:
                        db.add(EvidenceRelation(
                            claim_id=claim.id,
                            passage_id=evidence["passage_id"],
                            relation_type=evidence["relation_type"],
                            provenance_basis="model_inferred",
                            reviewer_status="unreviewed",
                            rationale=evidence["rationale"],
                        ))
                        stored_edges.append({
                            "passage_id": evidence["passage_id"],
                            "relation_type": evidence["relation_type"],
                            "rationale": evidence["rationale"],
                        })
                    persisted_claims.append({
                        "id": claim.id,
                        "statement": claim.statement,
                        "uncertainty_notes": claim.uncertainty_notes,
                        "evidence": stored_edges,
                    })
                db.commit()

        # Phase 3: immutable report snapshot and final job state.
        generated_at = datetime.now(timezone.utc).isoformat()
        with SessionLocal() as db:
            run = db.get(ResearchRun, run_id)
            if run is None:
                return
            latest = db.scalar(select(ReportVersion).where(ReportVersion.run_id == run_id).order_by(ReportVersion.version_number.desc()))
            report = ReportVersion(
                run_id=run_id,
                version_number=(latest.version_number + 1) if latest else 1,
                parent_version_id=latest.id if latest else None,
                title="Academic Discovery Snapshot",
                content_markdown=_markdown_report(
                    question, mode, saved_papers, provider_result.get("provider_errors", {}),
                    generated_at, persisted_claims, llm_note, synthesis_result, synthesis_note,
                ),
                evidence_snapshot={
                    "query": question,
                    "mode": mode,
                    "providers_requested": provider_result.get("providers_requested"),
                    "provider_errors": provider_result.get("provider_errors", {}),
                    "paper_ids": [paper["paper_id"] for paper in saved_papers],
                    "passage_ids": [paper["passage_id"] for paper in saved_papers if paper["passage_id"]],
                    "claim_ids": [claim["id"] for claim in persisted_claims],
                    "generated_at": generated_at,
                    "claim_verification_completed": False,
                    "llm_extraction_error": extraction_error,
                    "model_synthesis_completed": synthesis_result is not None,
                    "model_synthesis_error": synthesis_error,
                },
                change_summary="Initial scholarly discovery snapshot; extracted claims remain unreviewed candidates.",
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
                "claim_candidate_count": len(persisted_claims),
                "provider_errors": provider_result.get("provider_errors", {}),
                "llm_extraction_error": extraction_error,
                "claim_verification_completed": False,
            }
            db.commit()

    except Exception as exc:
        # Store a user-safe error; don't persist request URLs, headers or secrets.
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
