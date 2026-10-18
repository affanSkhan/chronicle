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
- **Worker durability:** research runs use FastAPI background tasks rather than a durable queue/worker. A server restart may interrupt an active run; retry/cancellation and persisted subtask progress are unfinished.
- **Temporal coverage:** external status check is user-triggered and a preview. There is no scheduled publisher/retraction-feed monitoring, exhaustive coverage or automatic authoritative status change.
- **Research Hypothesis Lab:** displays optional model-suggested candidate questions based on the current synthesis. It is not a graph-based novelty detector, and no prior-art recall or hypothesis-quality experiment has been performed.
- **PDF/records:** OCR for scanned PDFs, private cloud object storage, workspace deletion/retention controls and a full PDF report exporter are unfinished.
- **Production readiness:** no production deployment, monitoring/alerting, rate-limit/abuse controls, regular backup/restore validation or independently reviewed secure-cookie session model has been configured. JWT secret defaults are explicitly local-only; production setting rejects the known default secret.
- **Security testing:** API tests now include two-account isolation and private-route checks, but a comprehensive security review, prompt-injection evaluation, load test and privacy/retention audit remain outstanding.
- **Evaluation:** no reported benchmark results yet for SciFact/SciFact-Open, LitQA2, ScholarQABench, dependency precision/recall, contradiction per-class F1 or temporal impact precision/recall/false alarms.

All sample/demo content and model-assisted claims must be treated as unverified research assistance. No benchmark or scientific-accuracy result should be claimed without conducting and documenting the specified experiment.
