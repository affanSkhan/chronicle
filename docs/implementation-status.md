# Implementation status

Last updated: 2026-10-18

## Implemented in repository
- Next.js + TypeScript workspace UI for overview, research workspace, evidence graph concept, source timeline and hypothesis-lab concept.
- FastAPI application with health endpoint and typed request/response schemas.
- Durable SQLAlchemy models for projects, runs, papers, paper versions, studies, passages, claims, evidence relations, paper dependencies, source events and report versions.
- Alembic initial schema migration and local PostgreSQL Docker Compose configuration.
- Research project/run create/list/get endpoints backed by the configured database.
- Crossref/OpenAlex scholarly metadata search, DOI/external-ID de-duplication and paper import.
- PDF upload with type/size checks, PyMuPDF text extraction, SHA-256 deduplication and page-aware passage records.
- Claim creation, claim/passage relations, claim-to-claim dependencies, paper dependency records and persisted graph JSON endpoint.
- Report version creation/listing.
- Manual source-event ingestion with deterministic traversal to dependent papers, evidence-linked claims and report versions; affected records are flagged for review, not automatically declared false.
- API tests for parser behavior, CRUD validation, PDF ingestion and temporal source-event impact.
- GitHub Actions workflows for API tests and frontend lint/typecheck/build.

## Important limitation: demo versus research execution
Research-run endpoints currently persist the request with status queued and demo=true. A worker/orchestrator has not yet executed the research question against returned papers. Creating a run does not yet produce a verified literature report.
The frontend uses illustrative sample claims/graph/timeline for its dashboard panels. Academic search results and PDF ingestion are API-backed, but graph and timeline screens are not fully wired to live database data.

## Not implemented yet
- End-to-end research job worker and cancellation/retry.
- LLM-backed structured claim extraction, citation entailment and contextual contradiction assessment.
- Embeddings, hybrid passage retrieval and grounded report synthesis.
- Source-status polling/scheduled alerts.
- Persistent object storage for uploaded PDFs in cloud deployment.
- OCR for scanned PDFs.
- Authentication, access control and multi-user project isolation.
- Live graph and source-timeline frontend powered by stored records.
- Exportable Evidence Passport / report export.
- Deployment configuration and production observability.

All demo claims and graph edges must not be interpreted as actual scientific findings.
