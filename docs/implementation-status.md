# Chronicle implementation status

Last updated: 2026-10-19

This status separates completed prototype behavior from research objectives in the VIIT SRS. It is not a claim that all specified requirements have been satisfied.

## Implemented in the repository
- **Auth and data isolation:** account registration/login using Argon2 password hashes and signed bearer tokens; authenticated API routes; user ownership checks on projects, runs, papers, PDF passages, evidence links, reports and exports.
- **Workspace/run records:** persistent SQLAlchemy models, run status API, project APIs and owner-scoped run history.
- **Scholarly discovery:** Crossref and OpenAlex metadata search, DOI/external-ID normalization and deduplicated library import.
- **PDF ingestion:** file type/signature and byte-size checks, configurable 50 MB/300-page limits, PyMuPDF selectable-text extraction, page-aware passage records, SHA-256 deduplication and owner-scoped local storage paths.
- **Execution and report:** background discovery task persists paper metadata, abstract passages, run state and an Academic Discovery Snapshot with coverage limitations.
- **Optional model stage:** server-configured OpenAI-compatible structured claim extraction and synthesis. Returned passage references are checked against the supplied passage set. Generated claims/edges remain model-inferred/unreviewed, not independently verified.
- **Evidence graph/review:** persisted claim-to-passage and claim-to-claim relationships, paper-dependency links, a graph API/UI and human review actions. Accepted/rejected/needs-review transitions preserve review history.
- **Temporal review:** Crossref/OpenAlex status-check preview; manual source-event recording; dependency traversal; impacted claims/reports flagged for review; source-event history and impact summary.
- **Audit trail:** audit events record actor, time, target, action, previous/new values, reason and resolution status for run/project creation, claims/evidence relationships, review transitions, dependency records, report versions and source-event impact. Per-run audit API/UI and Passport export are available.
- **Version history and exports:** report-version creation/listing, selector and deterministic line-level comparison, Markdown and JSON Evidence Passport including source/version/passage/claim/dependency/event/report/audit snapshots.
- **Local stack and CI:** Dockerfiles, PostgreSQL/API/web Compose stack, Alembic configuration/migrations, example environment files and GitHub Actions for API tests, web lint/typecheck/build and container builds.

## Important limitations / not yet implemented
- **Not a full multi-agent system yet:** current executed flow is a bounded scholarly discovery pipeline, not the complete seven-layer planner/agent orchestration in the project proposal.
- **Not full-text verification:** Crossref/OpenAlex returns metadata and abstracts when available. No citation-entailment benchmarked verifier, full-text acquisition/appraisal, embeddings/hybrid retrieval or calibrated evidence-weight score exists.
- **Worker durability:** research runs use FastAPI background tasks rather than a durable queue/worker. In-process scheduled status monitoring is a single-process polling loop controlled by ENABLE_SCHEDULED_MONITORING; do not enable it on multiple API replicas until a distributed worker/leader lock is added. A separate hourly GitHub Actions workflow is available for sleeping/free hosted web services and requires the CHRONICLE_DATABASE_URL repository secret. A server restart can interrupt a research run; durable queue/retry/cancellation and persisted subtask progress are unfinished.
- **Temporal coverage:** Crossref/OpenAlex checks can be scheduled for papers opted into monitoring, but these public metadata feeds are incomplete and do not equal comprehensive publisher surveillance. New signals remain review prompts; the scheduler does not automatically change paper status or create SourceEvents.
- **Research Hypothesis Lab:** displays optional model-suggested candidate questions based on the current synthesis. It is not a graph-based novelty detector, and no prior-art recall or hypothesis-quality experiment has been performed.
- **PDF/records:** OCR for scanned PDFs, private cloud object storage, workspace deletion/retention controls and a full PDF report exporter are unfinished.
- **Deployment status:** a Render Free Blueprint and Neon-backed deployment runbook are committed, and a dedicated Neon project exists; the Render web services have not been created from that Blueprint, so there is no live public Chronicle URL yet. The free-tier design stores original PDF bytes on an ephemeral API filesystem until durable private object storage is implemented.
- **Production readiness:** no production/SLA deployment, monitoring/alerting, rate-limit/abuse controls, regular backup/restore validation or independently reviewed secure-cookie session model has been configured. JWT secret defaults are explicitly local-only; production setting rejects the known default secret.
- **Security testing:** API tests now include two-account isolation and private-route checks, but a comprehensive security review, prompt-injection evaluation, load test and privacy/retention audit remain outstanding.
- **Evaluation:** a deterministic labelled-JSONL evaluation harness and protocol are included, but no reported benchmark results yet for SciFact/SciFact-Open, LitQA2, ScholarQABench, dependency precision/recall, contradiction per-class F1 or temporal impact precision/recall/false alarms.

All sample/demo content and model-assisted claims must be treated as unverified research assistance. No benchmark or scientific-accuracy result should be claimed without conducting and documenting the specified experiment.


## SRS implementation pass: planning and citation verification

Branch: `feat/srs-research-planning-verification` (changes are staged for review; this note is not a claim of production deployment).

- Added a deterministic Research Planner with four distinct, bounded execution profiles. It creates mode-specific scholarly subqueries, selects a documented set of workflow modules, persists the plan with the run/report snapshot, and displays the plan in the report.
- The research runner now executes the planned Crossref/OpenAlex searches, merges duplicate DOI/title records across subqueries, retains the query trail, and uses the selected mode's focus in optional claim extraction and synthesis prompts.
- Added a model-assisted claim-to-passage verification API. It requires a configured server-side model, checks that evidence pointers refer to supplied passage IDs, records the result in the claim and audit trail, and always marks it for human review. A missing model configuration returns a clear service-unavailable response without changing the claim.
- Added tests for profile differentiation, query/source budgets, allowed citation-verdict labels, invalid passage-pointer downgrading, and provider response validation.

Remaining SRS gaps that are **not** completed by this pass include durable background jobs/cancellation, scanned-PDF OCR, automatic study-family inference from source text, a graph-based adversarial search agent, comprehensive evaluation on SciFact/ALCE/LitQA2/ScholarQABench, load/security tests, and production storage/monitoring. Live scholarly-provider and LLM behavior still requires configured external services.


- The Evidence Graph now exposes the citation-support verifier on a selected claim and displays its assessment, rationale, evidence passage IDs, context notes and uncertainty while preserving the human-review warning.
