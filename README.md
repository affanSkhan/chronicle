# Chronicle
### Temporal Evidence Intelligence for Scientific Research

Chronicle is the working name for the VIIT B.Tech major project **Multi-Agent Research Assistant with Explainable Reasoning**. The current prototype focuses on source discovery, passage-level evidence records, provenance-aware relationships, human review, temporal source-event impact analysis and reproducible report history.

> **Current status:** Working development prototype, not production-ready and not a scientific-truth verifier. It supports accounts and account-scoped records, Crossref/OpenAlex metadata search, selectable-text PDF ingestion, persistent discovery runs, optional evidence-bounded model drafts, an inspectable evidence graph, source-event impact propagation, a review audit trail and Markdown/JSON Evidence Passport exports.

## Core workflow
1. Register/sign in to a private Chronicle account.
2. Search Crossref/OpenAlex or upload a PDF.
3. Submit a research question. The current worker retrieves scholarly metadata, stores paper versions and abstract passages, and creates a versioned Academic Discovery Snapshot.
4. With a backend-configured OpenAI-compatible model, Chronicle can create candidate claims linked to retrieved passage IDs and a structured synthesis draft. These are always marked as unreviewed/model-inferred.
5. Inspect the stored graph, record/preview source status signals, review relationships, and record corrections/retractions/conflicting findings.
6. Chronicle traces recorded dependencies and flags affected claims/report versions for review, preserving actor, timestamp and before/after values in its audit trail.
7. View report history, compare Markdown revisions, and export an Evidence Passport.

Retrieved abstracts are not full-text appraisal. A missing graph link or metadata signal is not proof a source or relationship does not exist. Source changes request review; they do not automatically establish that dependent conclusions are false.

## Repository structure
```
apps/web/                 Next.js + TypeScript workspace UI
services/api/             FastAPI, auth, evidence and source services
services/api/migrations/  Alembic schema migrations
docs/                     Architecture and implementation-status notes
infra/docker-compose.yml  Local PostgreSQL, API and web stack
.github/workflows/        API, web and container CI
```

## Run locally with Docker
Prerequisites: Docker Desktop / Docker Compose.

```bash
# Copy the root environment template and keep the defaults for local development only
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

Open the workspace at http://localhost:3000, API docs at http://localhost:8000/docs, and health endpoint at http://localhost:8000/api/v1/health.

Local Docker Compose enables scheduled source-status checks by default (`ENABLE_SCHEDULED_MONITORING=true`). Direct API runs default to disabled and can opt in via `.env`. The scheduler is single-process; do not enable it on multiple replicas until a distributed worker/leader lock is implemented.

The default JWT and database secrets are for local development only. For any shared/public environment, set a strong random `JWT_SECRET_KEY` of at least 32 characters, a strong database password, HTTPS, and appropriate CORS origins. Uploaded files are stored in a local container volume and are not served directly by the API.

## Run the API directly
```bash
cd services/api
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Copy .env.example to .env and configure local DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

## Optional model-assisted extraction and synthesis
Configure these **on the backend only**:
- `OPENAI_API_KEY`
- `OPENAI_API_BASE` (defaults to the OpenAI-compatible API base)
- `OPENAI_MODEL`

With no key/model, scholarly discovery still runs in retrieval-only mode and saves a report with explicit limitations. Never place model API keys in `NEXT_PUBLIC_*` variables or source control.

## Main API surface
- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- `POST /api/v1/projects`, `GET /api/v1/projects`
- `POST /api/v1/research/runs` with `execute=true`, `GET /api/v1/research/runs`
- `GET /api/v1/sources/search?q=...`, `POST /api/v1/sources/papers`
- `POST /api/v1/documents/upload`, `GET /api/v1/documents/papers/{paper_id}/passages`
- `POST /api/v1/evidence/claims`, `POST /api/v1/evidence/claims/{claim_id}/relations`
- `PATCH /api/v1/evidence/relations/{relation_id}/review`
- `GET /api/v1/evidence/runs/{run_id}/graph`, `GET /api/v1/evidence/runs/{run_id}/audit`
- `GET /api/v1/sources/papers/{paper_id}/status-check` (preview only)
- `POST /api/v1/sources/papers/{paper_id}/events`, `GET /api/v1/sources/events`
- `GET /api/v1/evidence/runs/{run_id}/reports`
- `GET /api/v1/evidence/runs/{run_id}/passport?format=markdown|json`

## Tests
```bash
cd services/api
pytest -q
```
GitHub Actions runs API tests, frontend typecheck/lint/production build and Docker Compose/image-build checks.

## Current limitations
- The research executor is a FastAPI background task, not a durable job queue; a process restart can interrupt a run.
- Search is currently metadata/abstract-level; full-text verification, embeddings/hybrid retrieval and calibrated evidence-strength scoring are not implemented.
- Scheduled external source-status monitoring, OCR for scanned PDFs, run cancellation/retry, PDF export, hypothesis novelty evaluation and benchmark experiments are not implemented.
- Authentication uses short-lived signed bearer tokens held in browser session storage for this prototype. Production deployment needs a reviewed session/cookie design, rate limiting, abuse protection, secure secret management and operational monitoring.
- Uploaded files are in local/container storage; configure private durable object storage and retention/deletion workflows before public use.
- Research outputs and hypothesis suggestions are aids for human review, not claims of verified scientific truth.

See [docs/implementation-status.md](docs/implementation-status.md) for the current implementation boundary and [docs/evaluation-protocol.md](docs/evaluation-protocol.md) for the reproducible benchmark protocol.
