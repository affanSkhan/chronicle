# Chronicle
### Temporal Evidence Intelligence for Scientific Research

Chronicle is the working name for the VIIT B.Tech major project **Multi-Agent Research Assistant with Explainable Reasoning**. The current prototype focuses on source discovery, passage-level evidence records, provenance-aware relationships, human review, temporal source-event impact analysis and reproducible report history.

> **Current status:** Deployed academic research prototype, not a scientific-truth verifier. It supports account-scoped workspaces, Crossref/OpenAlex/Semantic Scholar and public-web discovery adapters, uploaded-PDF ingestion and passage retrieval, four bounded research modes, optional model-assisted claims and synthesis, reviewable conclusion records, a provenance evidence graph, source-event impact/versioning, audit history, and Markdown/JSON/PDF Evidence Passport exports. Production deployments are registered READY; full live end-to-end acceptance and labelled benchmark efficacy remain in progress.

## Core workflow
1. Register/sign in to a private Chronicle account.
2. Search Crossref/OpenAlex or upload a PDF.
3. Submit a research question. The API executes a bounded, mode-specific plan, retrieves scholarly metadata and selected PDF passages, and creates a versioned Academic Discovery Snapshot. B–D evaluation runs can perform up to two recorded evidence-gap follow-up searches; A is a single-query baseline.
4. With a backend-configured OpenAI-compatible model, Chronicle can create candidate claims linked to retrieved passage IDs and a structured synthesis draft. These are always marked as unreviewed/model-inferred.
5. Inspect the stored graph, review claims, conclusions and relationships, check source status, and record corrections/retractions/conflicting findings. Model-derived conclusions and provenance edges begin in a review-required state; a human review decision is audit-logged.
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

Open the workspace at http://localhost:3000, API docs at http://localhost:8000/docs, and liveness endpoint at http://localhost:8000/api/v1/health and database-readiness endpoint at http://localhost:8000/api/v1/ready.

Local Docker Compose enables scheduled source-status checks by default (`ENABLE_SCHEDULED_MONITORING=true`). Direct API runs default to disabled and can opt in via `.env`. The scheduler is single-process; do not enable it on multiple replicas until a distributed worker/leader lock is implemented.

The default JWT and database secrets are for local development only. For any shared/public environment, set a strong random `JWT_SECRET_KEY` of at least 32 characters, a strong database password, HTTPS, and appropriate CORS origins. Uploaded files are stored in a local container volume and are not served directly by the API.

## Full Vercel deployment (frontend + API)

For hosting the Next.js frontend and FastAPI backend as two Vercel projects while keeping PostgreSQL on Neon, follow [docs/deployment-vercel.md](docs/deployment-vercel.md). It covers Vercel project settings, environment variables, an explicit database migration workflow, and current file-upload/runtime limits.

## Free-tier hosted demo

A dedicated [Render Blueprint](render.yaml) is included for the API and Next.js frontend, with PostgreSQL hosted separately in Neon. Follow [docs/deployment-free-tier.md](docs/deployment-free-tier.md) to apply the Blueprint and configure the `DATABASE_URL` secret. The current hosted-demo design keeps the API worker scheduler off on free Render (free instances sleep); the optional hourly GitHub Actions workflow requires the repository Actions secret `CHRONICLE_DATABASE_URL`.

Free-tier hosting is for a demonstrator, not production. Original uploaded PDFs are currently stored on the API filesystem and may be lost on restart/redeploy/spin-down even though extracted passages and other relational records persist in Neon.

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

## Free model-assisted extraction and synthesis

Chronicle can use Groq's free tier through its OpenAI-compatible API:
- `LLM_API_KEY`: create a free key at https://console.groq.com/keys
- `LLM_API_BASE=https://api.groq.com/openai/v1`
- `LLM_MODEL=openai/gpt-oss-20b`

No payment method or purchased credits are required for this configuration. The free plan has request/token limits, so Chronicle bounds prompts and response length. If the provider quota is reached, use retrieval-only workflows until it resets. Claims, synthesis, and citation assessments remain unverified drafts for human review.

Google Gemini is another free-tier option: use a currently free-tier model ID, a Google AI Studio key, and `LLM_API_BASE=https://generativelanguage.googleapis.com/v1beta/openai/`. Google may use free-tier prompts and responses to improve its products, so do not send confidential material through that option.

Legacy `OPENAI_API_KEY`, `OPENAI_API_BASE`, and `OPENAI_MODEL` variables remain supported. OpenAI API use is billed separately from ChatGPT. Never put model API keys in `NEXT_PUBLIC_*` variables or source control.

## Main API surface
- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- `POST /api/v1/projects`, `GET /api/v1/projects`
- `POST /api/v1/research/runs` with `execute=true`, `GET /api/v1/research/runs`
- `GET /api/v1/sources/search?q=...`, `POST /api/v1/sources/papers`
- `POST /api/v1/documents/upload`, `GET /api/v1/documents/papers/{paper_id}/passages`
- `POST /api/v1/evidence/claims`, `POST /api/v1/evidence/claims/{claim_id}/relations`
- `PATCH /api/v1/evidence/relations/{relation_id}/review`
- `GET /api/v1/evidence/runs/{run_id}/graph`, `GET /api/v1/evidence/runs/{run_id}/audit`
- `GET /api/v1/evidence/runs/{run_id}/conclusions`, `PATCH /api/v1/evidence/conclusions/{conclusion_id}/review` (persisted report findings and human review)
- `GET /api/v1/sources/papers/{paper_id}/status-check` (preview only)
- `POST /api/v1/sources/papers/{paper_id}/events`, `GET /api/v1/sources/events`
- `GET /api/v1/evidence/runs/{run_id}/reports`
- `GET /api/v1/evidence/runs/{run_id}/passport?format=markdown|json|pdf` (includes versioned conclusions and their passage/claim provenance edges)

## Tests
```bash
cd services/api
pytest -q
```
GitHub Actions runs API tests, frontend typecheck/lint/production build and Docker Compose/image-build checks.

## Current limitations
- The default Vercel executor is inline/in-process; an optional PostgreSQL queue worker exists for separate Docker deployment, but a continuously running worker is not deployed on Vercel. In-process runs can be interrupted by a function/process restart.
- External academic adapters primarily return metadata and abstracts; publisher full-text acquisition and systematic full-text appraisal are not implemented. Hybrid BM25 plus dense reranking is optional and requires Hugging Face configuration; dense passage vectors are not persistently indexed.
- OCR is a bounded fallback, not a guarantee of accurate scanned-text extraction. A–D evaluation arms and a metrics harness exist, but labelled SciFact/SciFact-Open experiments, ALCE-style citation-quality evaluations, and the adjudicated temporal-update study have not yet produced reproducible results. Scheduled source monitoring and post-update reassessment remain bounded and human-led rather than a fully autonomous evidence-gap/temporal-agent loop.
- Authentication uses short-lived signed bearer tokens held in browser session storage for this prototype. Production deployment needs a reviewed session/cookie design, rate limiting, abuse protection, secure secret management and operational monitoring.
- Vercel PDF uploads are capped at 3 MB until direct-to-object-storage upload is implemented. Production originals use private S3-compatible storage when configured or the private PostgreSQL blob table otherwise. Application-level deletion removes source-derived conclusions and report text, but backup and third-party provider retention policies remain outside that deletion path.
- Research outputs and hypothesis suggestions are aids for human review, not claims of verified scientific truth.

See [docs/implementation-status.md](docs/implementation-status.md) for the current implementation boundary, [docs/evaluation-protocol.md](docs/evaluation-protocol.md) for the reproducible benchmark protocol, and [docs/deployment-free-tier.md](docs/deployment-free-tier.md) for the free-tier deployment runbook.
