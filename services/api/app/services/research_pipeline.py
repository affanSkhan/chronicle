"""Background research runner: scholarly discovery plus optional structured extraction.

Model-generated claims remain unreviewed. Each edge is checked against the
passage IDs supplied to the model and labelled model-inferred, not verified.
"""
from datetime import datetime, timezone
import asyncio
import math
import hashlib
import re

from sqlalchemy import func, select

from app.core.config import get_llm_config, get_settings
from app.core.database import SessionLocal
from app.models.entities import Claim, EvidenceRelation, Paper, PaperVersion, Passage, ReportVersion, ResearchRun, Study
from app.services.academic_search import search_papers
from app.services.audit import record_audit_event
from app.services.claim_extraction import extract_claims_from_passages
from app.services.evidence_synthesis import synthesize_evidence
from app.services.dependency_candidates import build_dependency_clusters, suggest_dependency_candidates
from app.services.research_planner import build_research_plan, focus_for_mode


class ResearchRunCancelled(Exception):
    """Raised internally when the owner requests cooperative run cancellation."""


def _run_cancellation_requested(run_id: str) -> bool:
    with SessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        return run is None or run.status in {"cancel_requested", "cancelled"}


def _finalize_cancelled_run(run_id: str, reason: str = "Owner requested cancellation.") -> None:
    with SessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        if run is None:
            return
        previous_status = run.status
        if run.status != "cancelled":
            now = datetime.now(timezone.utc)
            run.status = "cancelled"
            run.cancel_requested_at = run.cancel_requested_at or now
            run.cancelled_at = now
            run.error_message = None
            run.configuration = {
                **(run.configuration or {}),
                "cancellation": {
                    **((run.configuration or {}).get("cancellation") or {}),
                    "finalized_at": now.isoformat(),
                    "previous_status": previous_status,
                    "reason": reason,
                },
            }
            record_audit_event(
                db,
                actor_user_id=None,
                run_id=run.id,
                target_entity_type="research_run",
                target_entity_id=run.id,
                action="research_run.cancelled",
                previous_value={"status": previous_status},
                new_value={"status": "cancelled", "cancelled_at": now.isoformat()},
                reason=reason,
                resolution_status="cancelled",
            )
        db.commit()


async def _await_with_cancellation(awaitable, run_id: str):
    """Await an external stage while polling for owner cancellation."""
    if _run_cancellation_requested(run_id):
        raise ResearchRunCancelled("Research run cancellation was requested.")
    task = asyncio.create_task(awaitable)
    while not task.done():
        if _run_cancellation_requested(run_id):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise ResearchRunCancelled("Research run cancellation was requested.")
        await asyncio.wait({task}, timeout=0.5)
    if _run_cancellation_requested(run_id):
        raise ResearchRunCancelled("Research run cancellation was requested.")
    return task.result()


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
    study_contexts: list[dict],
    execution_plan: dict | None = None,
    dependency_candidates: list[dict] | None = None,
    dependency_analysis: dict | None = None,
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
    if execution_plan:
        plan_lines = [
            "",
            "## Execution plan",
            "",
            f"- **Profile:** {execution_plan.get('profile_label', mode)}",
            f"- **Planner version:** {execution_plan.get('version', '1.0')}",
            f"- **Source budget:** {execution_plan.get('source_budget', len(papers))}",
            "- **Search subqueries actually executed:**",
        ]
        plan_lines.extend(f"  - {query}" for query in execution_plan.get("queries", []))
        plan_lines.append("- **Workflow modules:**")
        plan_lines.extend(f"  - {module}" for module in execution_plan.get("modules", []))
        plan_lines.extend(["", f"**Mode focus:** {execution_plan.get('focus', 'General scholarly discovery')}", ""])
        insert_at = lines.index("## Important interpretation note")
        lines[insert_at:insert_at] = plan_lines

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
        lines.extend(["### Extracted study context", ""])
        if not study_contexts:
            lines.append("No source-linked structured study-context records were extracted for this run.")
        else:
            lines.append("The following context fields were extracted from the linked abstract passages. Model-inferred fields remain unreviewed and may omit information available only in the full paper.")
            lines.append("")
            for item in study_contexts:
                source = next((paper for paper in papers if paper.get("paper_id") == item.get("paper_id")), None)
                title = source.get("title") if source else item.get("paper_id", "Unknown paper")
                lines.append(f"- **{title}** · study record `{item['id']}` · abstract passage `{item.get('source_passage_id') or 'unavailable'}`")
                for field, label in (("study_type", "Study type"), ("population", "Population"), ("method", "Method"), ("intervention", "Intervention")):
                    if item.get(field):
                        lines.append(f"  - {label}: {item[field]}")
                if item.get("outcomes"):
                    lines.append("  - Outcomes: " + "; ".join(item["outcomes"]))
                if item.get("limitations"):
                    lines.append("  - Limitations: " + "; ".join(item["limitations"]))
                lines.append(f"  - Extraction basis: {item.get('extraction_basis', 'unreviewed')}")
            lines.append("")
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
        opportunities = synthesis.get("research_opportunities", [])
        if opportunities:
            lines.extend(["", "### Evidence-linked research opportunities (not novelty claims)", ""])
            for index, opportunity in enumerate(opportunities, start=1):
                lines.append(f"{index}. **{opportunity.get('question', 'Candidate research question')}**")
                if opportunity.get("rationale"):
                    lines.append(f"   - Motivation: {opportunity['rationale']}")
                for passage_id in opportunity.get("evidence_passage_ids", []):
                    paper = next((item for item in papers if item.get("passage_id") == passage_id), None)
                    if paper:
                        doi = _normalize_doi(paper.get("doi"))
                        source_url = f"https://doi.org/{doi}" if doi else (paper.get("landing_url") or "")
                        title = paper.get("title") or "Source paper"
                        source_label = f"[{title}]({source_url})" if source_url else title
                        lines.append(f"   - Evidence trace: {source_label} · passage ID {passage_id}")
                    else:
                        lines.append(f"   - Evidence trace: passage ID {passage_id}")
                if opportunity.get("prior_art_search_queries"):
                    lines.append("   - Prior-art search queries: " + " | ".join(opportunity["prior_art_search_queries"]))
                if opportunity.get("alternative_explanations"):
                    lines.append("   - Alternative explanations: " + "; ".join(opportunity["alternative_explanations"]))
                if opportunity.get("falsification_plan"):
                    lines.append("   - Falsification plan: " + opportunity["falsification_plan"])
                lines.append("   - Status: candidate only; prior-art search and human review are required.")
                lines.append("")
        lines.extend(["", "**Uncertainty:** " + synthesis.get("uncertainty_statement", "Uncertainty was not provided."), ""])
    lines.append(synthesis_note)
    lines.append("")

    if execution_plan and execution_plan.get("stages", {}).get("dependency_candidate_scan"):
        analysis = dependency_analysis or {}
        lines.extend(["## Potential source-dependence analysis (heuristic; human review required)", ""])
        lines.append(f"- Raw retrieved source records: {analysis.get('raw_source_count', len(papers))}")
        lines.append(f"- Candidate links surfaced: {analysis.get('candidate_link_count', len(dependency_candidates or []))}")
        lines.append(f"- Candidate dependency clusters: {analysis.get('candidate_cluster_count', 0)}")
        lines.append(f"- Sources outside candidate clusters: {analysis.get('unclustered_source_count', len(papers))}")
        lines.append("- Unclustered sources are not proven independent, and clustered sources are not proven dependent.")
        lines.append("")
        clusters = analysis.get("clusters", [])
        if clusters:
            for cluster in clusters:
                lines.append(f"### Candidate cluster · {cluster['source_count']} source records")
                lines.append("Members: " + "; ".join(cluster.get("paper_titles", [])))
                lines.append("Candidate link types: " + ", ".join(cluster.get("relation_types", [])))
                lines.append("Signals: " + "; ".join(cluster.get("signals", [])))
                lines.append(f"Review state: {cluster.get('status', 'candidate_requires_human_review')}")
                lines.append(f"Interpretation: {cluster.get('interpretation', 'Manual source-lineage review required.')}")
                lines.append("")
        elif not dependency_candidates:
            lines.append("No candidate dependency links were surfaced by the current heuristic set. This does not establish source independence.")
            lines.append("")
        if dependency_candidates:
            lines.extend(["### Individual candidate links", ""])
            for candidate in dependency_candidates:
                lines.append(f"- **{candidate['relation_type'].replace('_', ' ').title()}:** {candidate['paper_a_title']} ↔ {candidate['paper_b_title']}")
                lines.append("  - Signal: " + "; ".join(candidate.get("signals", [])))
                lines.append(f"  - Heuristic score (not a calibrated probability): {candidate.get('confidence', 0)}")
                lines.append(f"  - Rationale: {candidate.get('rationale', '')}")
                lines.append("  - Status: candidate only; researcher confirmation is required.")
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


async def _execute_planned_search(
    question: str,
    mode: str,
    max_sources: int,
    plan: dict | None = None,
    run_id: str | None = None,
) -> tuple[dict, dict]:
    """Run bounded planned searches and cancel pending requests when requested."""
    plan = plan or build_research_plan(question, mode, max_sources)
    queries = plan["queries"]
    per_query_limit = max(1, math.ceil(max_sources / max(1, len(queries))))
    tasks = {
        asyncio.create_task(search_papers(query, limit=per_query_limit, provider="all")): index
        for index, query in enumerate(queries)
    }
    responses: list[dict | Exception | None] = [None] * len(queries)
    pending = set(tasks)
    while pending:
        if run_id and _run_cancellation_requested(run_id):
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise ResearchRunCancelled("Research run cancellation was requested.")
        done, pending = await asyncio.wait(
            pending,
            timeout=0.5,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            try:
                responses[tasks[task]] = task.result()
            except Exception as exc:
                responses[tasks[task]] = exc
    if run_id and _run_cancellation_requested(run_id):
        raise ResearchRunCancelled("Research run cancellation was requested.")

    provider_errors: dict[str, str] = {}
    merged: dict[str, dict] = {}
    successful_queries = 0
    for index, (query, response) in enumerate(zip(queries, responses), start=1):
        if isinstance(response, Exception) or response is None:
            provider_errors[f"query_{index}"] = "This planned search failed or a provider was unavailable."
            continue
        successful_queries += 1
        for name, message in (response.get("provider_errors") or {}).items():
            provider_errors[f"query_{index}_{name}"] = message
        for raw_item in response.get("results", []):
            item = dict(raw_item)
            doi = _normalize_doi(item.get("doi"))
            normalized_title = " ".join(str(item.get("title") or "").lower().split())
            key = f"doi:{doi.lower()}" if doi else f"title:{normalized_title}"
            if not normalized_title:
                continue
            if key not in merged:
                item["matched_queries"] = [query]
                merged[key] = item
            else:
                prior = merged[key]
                prior["abstract"] = prior.get("abstract") or item.get("abstract")
                prior["authors"] = prior.get("authors") or item.get("authors") or []
                prior["landing_url"] = prior.get("landing_url") or item.get("landing_url")
                prior["publisher"] = prior.get("publisher") or item.get("publisher")
                prior["publication_year"] = prior.get("publication_year") or item.get("publication_year")
                prior["doi"] = prior.get("doi") or item.get("doi")
                prior["matched_queries"] = sorted(set(prior.get("matched_queries", []) + [query]))
    if successful_queries == 0:
        raise RuntimeError("All planned scholarly searches failed.")

    result_items = list(merged.values())
    result_items.sort(
        key=lambda item: (
            item.get("publication_year") or 0,
            bool(item.get("abstract")),
            str(item.get("title") or "").lower(),
        ),
        reverse=True,
    )
    result_items = result_items[:max_sources]
    provider_result = {
        "query": question,
        "queries": queries,
        "providers_requested": "all",
        "results": result_items,
        "provider_errors": provider_errors,
        "execution_plan": plan,
        "note": "Mode-specific metadata retrieval; abstracts remain source text, not claim verification.",
    }
    return provider_result, plan


async def execute_research_run(run_id: str) -> None:
    """Execute a discovery run and persist its status, source records and report."""
    cancel_before_start = False
    with SessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        if run is None:
            return
        if run.status in {"cancel_requested", "cancelled"}:
            cancel_before_start = True
        else:
            run.status = "running"
            run.demo = False
            run.error_message = None
            run.configuration = {
                **(run.configuration or {}),
                "pipeline": "mode-specific-scholarly-discovery",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            question = run.question
            limit = run.max_sources
            mode = run.mode
            owner_user_id = run.owner_user_id
            db.commit()
    if cancel_before_start:
        _finalize_cancelled_run(run_id, "Run was cancelled before the worker began.")
        return

    try:
        execution_plan = build_research_plan(question, mode, limit)
        # Persist the plan before network I/O so a failed or partial run remains inspectable.
        with SessionLocal() as db:
            run = db.get(ResearchRun, run_id)
            if run is None:
                return
            run.configuration = {
                **(run.configuration or {}),
                "pipeline": "mode-specific-scholarly-discovery",
                "planner_version": execution_plan["version"],
                "execution_plan": execution_plan,
                "planned_search_queries": execution_plan["queries"],
            }
            db.commit()

        provider_result, execution_plan = await _execute_planned_search(
            question, mode, limit, plan=execution_plan, run_id=run_id
        )
        if _run_cancellation_requested(run_id):
            raise ResearchRunCancelled("Research run cancellation was requested.")
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
                    paper = db.scalar(select(Paper).where(func.lower(Paper.doi) == doi.lower(), Paper.owner_user_id == owner_user_id))
                if paper is None and item.get("external_id"):
                    paper = db.scalar(select(Paper).where(
                        Paper.source_provider == item.get("provider", "unknown"),
                        Paper.external_id == item.get("external_id"),
                        Paper.owner_user_id == owner_user_id,
                    ))

                if paper is None:
                    paper = Paper(
                        owner_user_id=owner_user_id,
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
                            "search_queries": item.get("matched_queries") or [question],
                            "planner_version": execution_plan.get("version", "1.0"),
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
                        "paper_id": paper.id,
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
        if _run_cancellation_requested(run_id):
            raise ResearchRunCancelled("Research run cancellation was requested.")
        settings = get_settings()
        extracted_claims: list[dict] = []
        stages = execution_plan.get("stages", {})
        should_extract_claims = bool(stages.get("claim_extraction", True))
        should_synthesize_evidence = bool(stages.get("evidence_synthesis", True))
        should_scan_dependencies = bool(stages.get("dependency_candidate_scan", False))
        llm_note = ("Claim extraction skipped by the Quick Discovery profile; this run is retrieval-only."
                    if not should_extract_claims else
                    "LLM extraction skipped because LLM_API_KEY and LLM_MODEL are not both configured.")
        extraction_error: str | None = None
        api_key, api_base, model_name = get_llm_config(settings)
        model_question = question + "\n\nRun profile: " + execution_plan["profile_label"] + ". Focus: " + focus_for_mode(mode)
        if should_extract_claims and api_key and model_name and passages_for_extraction:
            try:
                extracted_claims = await _await_with_cancellation(extract_claims_from_passages(
                    question=model_question,
                    passages=passages_for_extraction,
                    api_key=api_key,
                    api_base=api_base,
                    model=settings.openai_model.strip(),
                ), run_id)
                llm_note = "Structured extraction completed; generated claims and evidence edges still require human review."
            except Exception as exc:
                extraction_error = type(exc).__name__
                llm_note = "LLM extraction failed; the bibliographic discovery report was completed without model-generated claims."

        synthesis_result: dict | None = None
        synthesis_note = ("Synthesis skipped by the Quick Discovery profile to keep this run retrieval-only."
                          if not should_synthesize_evidence else
                          "Model synthesis skipped because LLM_API_KEY and LLM_MODEL are not both configured.")
        synthesis_error: str | None = None
        if should_synthesize_evidence and api_key and settings.openai_model.strip() and passages_for_extraction:
            try:
                synthesis_result = await _await_with_cancellation(synthesize_evidence(
                    question=model_question,
                    passages=passages_for_extraction,
                    api_key=api_key,
                    api_base=settings.openai_api_base,
                    model=settings.openai_model.strip(),
                ), run_id)
                synthesis_note = "Model synthesis completed; draft findings and candidate research questions still require human review."
            except Exception as exc:
                synthesis_error = type(exc).__name__
                synthesis_note = "Model synthesis failed; the bibliographic discovery report was completed without it."

        persisted_studies: list[dict] = []
        if synthesis_result and synthesis_result.get("study_characterizations"):
            source_by_passage = {str(item["id"]): item for item in passages_for_extraction}
            with SessionLocal() as db:
                for characterization in synthesis_result.get("study_characterizations", []):
                    passage_id = str(characterization.get("passage_id") or "")
                    source = source_by_passage.get(passage_id)
                    if source is None:
                        continue
                    values = {
                        "study_type": characterization.get("study_type"),
                        "population": characterization.get("population"),
                        "method": characterization.get("method"),
                        "intervention": characterization.get("intervention"),
                        "outcomes": characterization.get("outcomes") or [],
                        "limitations": characterization.get("limitations") or [],
                    }
                    if not any([values["study_type"], values["population"], values["method"], values["intervention"], values["outcomes"], values["limitations"]]):
                        continue
                    study = db.scalar(select(Study).where(Study.source_passage_id == passage_id))
                    if study is None:
                        study = Study(
                            paper_id=source["paper_id"],
                            source_passage_id=passage_id,
                            **values,
                            extraction_basis="model_inferred",
                        )
                        db.add(study)
                        db.flush()
                        record_audit_event(
                            db,
                            actor_user_id=None,
                            run_id=run_id,
                            target_entity_type="study",
                            target_entity_id=study.id,
                            action="study.context_extracted",
                            previous_value=None,
                            new_value={
                                "paper_id": study.paper_id,
                                "source_passage_id": study.source_passage_id,
                                **values,
                                "extraction_basis": study.extraction_basis,
                            },
                            reason="Optional model extraction generated candidate study context from an abstract passage.",
                            resolution_status="needs_review",
                        )
                    persisted_studies.append({
                        "id": study.id,
                        "paper_id": study.paper_id,
                        "source_passage_id": study.source_passage_id,
                        "study_type": study.study_type,
                        "population": study.population,
                        "method": study.method,
                        "intervention": study.intervention,
                        "outcomes": study.outcomes or [],
                        "limitations": study.limitations or [],
                        "extraction_basis": study.extraction_basis,
                    })
                db.commit()

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

        dependency_candidates: list[dict] = []
        dependency_analysis: dict = {
            "status": "not_scanned",
            "raw_source_count": len(saved_papers),
            "candidate_link_count": 0,
            "candidate_cluster_count": 0,
            "clustered_source_count": 0,
            "unclustered_source_count": None,
            "clusters": [],
            "interpretation": "This mode does not run the dependency-candidate scan. No independence conclusion is implied.",
        }
        if should_scan_dependencies:
            # Forensic scanning is bounded to this run and does not persist any graph edges.
            if owner_user_id and len(saved_papers) >= 2:
                with SessionLocal() as db:
                    dependency_candidates = suggest_dependency_candidates(
                        db,
                        owner_user_id,
                        limit=30,
                        paper_ids={paper["paper_id"] for paper in saved_papers},
                    )
            dependency_analysis = build_dependency_clusters(saved_papers, dependency_candidates)

        provider_errors = provider_result.get("provider_errors", {})
        llm_stage_expected = should_extract_claims or should_synthesize_evidence
        llm_provider_unavailable = llm_stage_expected and (not api_key or not settings.openai_model.strip())
        has_limitations = bool(provider_errors) or bool(extraction_error) or bool(synthesis_error) or not saved_papers or llm_provider_unavailable
        completion_status = "completed_with_limitations" if has_limitations else "completed"

        # Phase 3: immutable report snapshot and final job state.
        if _run_cancellation_requested(run_id):
            raise ResearchRunCancelled("Research run cancellation was requested.")
        generated_at = datetime.now(timezone.utc).isoformat()
        with SessionLocal() as db:
            run = db.get(ResearchRun, run_id)
            if run is None:
                return
            latest = db.scalar(select(ReportVersion).where(ReportVersion.run_id == run_id).order_by(ReportVersion.version_number.desc()))
            if run.status in {"cancel_requested", "cancelled"}:
                db.rollback()
                raise ResearchRunCancelled("Research run cancellation was requested before report commit.")
            report = ReportVersion(
                run_id=run_id,
                version_number=(latest.version_number + 1) if latest else 1,
                parent_version_id=latest.id if latest else None,
                title="Academic Discovery Snapshot",
                content_markdown=_markdown_report(
                    question, mode, saved_papers, provider_result.get("provider_errors", {}),
                    generated_at, persisted_claims, llm_note, synthesis_result, synthesis_note, persisted_studies,
                    execution_plan=execution_plan,
                    dependency_candidates=dependency_candidates,
                    dependency_analysis=dependency_analysis,
                ),
                evidence_snapshot={
                    "query": question,
                    "mode": mode,
                    "execution_plan": execution_plan,
                    "executed_search_queries": provider_result.get("queries", []),
                    "providers_requested": provider_result.get("providers_requested"),
                    "provider_errors": provider_result.get("provider_errors", {}),
                    "paper_ids": [paper["paper_id"] for paper in saved_papers],
                    "passage_ids": [paper["passage_id"] for paper in saved_papers if paper["passage_id"]],
                    "claim_ids": [claim["id"] for claim in persisted_claims],
                    "study_ids": [study["id"] for study in persisted_studies],
                    "generated_at": generated_at,
                    "claim_verification_completed": False,
                    "llm_extraction_error": extraction_error,
                    "model_synthesis_completed": synthesis_result is not None,
                    "model_synthesis_error": synthesis_error,
                    "model_synthesis_note": synthesis_note,
                    "model_synthesis": synthesis_result,
                    "dependency_candidates": dependency_candidates,
                    "source_dependence_analysis": dependency_analysis,
                    "completion_status": completion_status,
                    "completed_with_limitations": has_limitations,
                },
                change_summary="Initial scholarly discovery snapshot; extracted claims remain unreviewed candidates.",
            )
            db.add(report)
            run.status = completion_status
            run.demo = False
            run.error_message = None
            run.configuration = {
                **(run.configuration or {}),
                "pipeline": "mode-specific-scholarly-discovery",
                "execution_plan": execution_plan,
                "executed_search_queries": provider_result.get("queries", []),
                "completed_at": generated_at,
                "paper_count": len(saved_papers),
                "passage_count": sum(1 for paper in saved_papers if paper["passage_id"]),
                "claim_candidate_count": len(persisted_claims),
                "study_context_count": len(persisted_studies),
                "dependency_candidate_count": len(dependency_candidates),
                "source_dependence_analysis": dependency_analysis,
                "provider_errors": provider_result.get("provider_errors", {}),
                "llm_extraction_error": extraction_error,
                "claim_verification_completed": False,
                "completion_status": run.status,
                "completed_with_limitations": has_limitations,
            }
            db.commit()

    except ResearchRunCancelled:
        _finalize_cancelled_run(run_id)
    except Exception as exc:
        # A concurrent cancellation takes precedence over a generic provider error.
        # Store user-safe errors; never persist request URLs, headers or secrets.
        with SessionLocal() as db:
            run = db.get(ResearchRun, run_id)
            if run is not None:
                if run.status in {"cancel_requested", "cancelled"}:
                    now = datetime.now(timezone.utc)
                    previous_status = run.status
                    run.status = "cancelled"
                    run.cancel_requested_at = run.cancel_requested_at or now
                    run.cancelled_at = now
                    run.error_message = None
                    run.configuration = {
                        **(run.configuration or {}),
                        "cancellation": {
                            **((run.configuration or {}).get("cancellation") or {}),
                            "finalized_at": now.isoformat(),
                            "reason": "Cancellation was observed while handling a provider failure.",
                        },
                    }
                    record_audit_event(
                        db,
                        actor_user_id=None,
                        run_id=run.id,
                        target_entity_type="research_run",
                        target_entity_id=run.id,
                        action="research_run.cancelled",
                        previous_value={"status": previous_status},
                        new_value={"status": "cancelled", "cancelled_at": now.isoformat()},
                        reason="Cancellation was observed while handling a provider failure.",
                        resolution_status="cancelled",
                    )
                else:
                    run.status = "failed"
                    run.demo = False
                    run.error_message = "Scholarly discovery failed. Check provider availability and server logs."
                    run.configuration = {
                        **(run.configuration or {}),
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                        "failure_type": type(exc).__name__,
                    }
                db.commit()
