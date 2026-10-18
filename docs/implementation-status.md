# Implementation status

Last updated: 2026-10-18

## Implemented
- Next.js/TypeScript workspace with overview, research workspace, academic metadata search, PDF upload, report rendering, evidence graph, source timeline and Hypothesis Lab.
- FastAPI API with SQLAlchemy models and Alembic bootstrap migration for projects, runs, papers/versions, studies, passages, claims, evidence relations, paper dependencies, source events and report versions.
- Crossref/OpenAlex metadata discovery and normalized/de-duplicated paper-library import.
- PDF upload validation, SHA-256 duplicate detection, selectable-text extraction, page-aware passage storage and bounded upload size.
- Executable background discovery pipeline that persists paper metadata, abstract passages, run state and a versioned Academic Discovery Snapshot.
- Optional OpenAI-compatible structured claim extraction and evidence-bounded synthesis. Every generated claim is labelled unreviewed/model-inferred; supplied passage references are validated. Abstract-only synthesis is explicitly not full-text review.
- Evidence relation review endpoint and UI actions; accepted relations become human-reviewed and can update the claim's assessment label.
- Persisted evidence graph endpoint with paper/versions/passages/claims and dependency edges.
- Report version history selector and deterministic line-level Markdown comparison.
- Manual source-event registration, Crossref/OpenAlex status preview, dependency traversal, affected-claim/report review flags and source-event history.
- Markdown and JSON Evidence Passport export containing source records, report snapshots, claim-to-passage relationships, review state and temporal events.
- Dockerfiles for API and web, Docker Compose full stack, upload/database volumes and GitHub Actions CI workflows.
- Automated API tests for validation, search parsers, PDF ingestion, run/pipeline persistence, human review, graph lineage, temporal impact and Evidence Passport.

## Important limitations
- Crossref/OpenAlex search returns bibliographic metadata and abstracts; it does not provide guaranteed full-text access or exhaustive scholarly coverage.
- The current LLM stage is optional and uses a server-configured OpenAI-compatible model. Without those settings the system runs in retrieval-only mode.
- Model-generated claims and synthesis findings remain candidates, not independently verified scientific conclusions.
- The research run uses FastAPI BackgroundTasks, not a durable task queue. A server restart during a run may interrupt it; add a persistent queue/worker before production use.
- Scanned-PDF OCR is not implemented.
- Crossref/OpenAlex status check is a preview for a researcher. It does not automatically monitor all publishers on a schedule or automatically assert that a paper is retracted. Manual event submission triggers impact propagation.
- Graph and timeline are backed by persisted data, but the hypothesis discovery algorithm is not yet an autonomous graph-based novelty detector.
- Authentication, per-user access controls, durable cloud object storage, rate limiting, production logging/metrics, backup/restore, and production deployment configuration are not complete.

All demo records remain illustrative and must not be interpreted as scientific findings.
