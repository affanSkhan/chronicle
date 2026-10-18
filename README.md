# Chronicle
### Temporal Evidence Intelligence for Scientific Research

Chronicle is a research assistant prototype for evidence-centred scientific discovery. It connects claims to retrieved source passages, records provenance and source dependencies, preserves report versions, and flags dependent claims for review when a source event is recorded.

> **Current implementation status:** Working development slice, not a production-ready scientific verifier. Crossref/OpenAlex metadata search, paper-library import, selectable-text PDF ingestion, report persistence, graph relationships, manual source-event impact propagation, optional evidence-bounded synthesis, and Evidence Passport export are implemented. Full-text claim verification, scheduled source monitoring, OCR, authentication and production deployment remain incomplete.

## Core workflow
1. Search Crossref/OpenAlex or upload a research PDF.
2. Create a research run. The executable pipeline retrieves scholarly metadata and stores abstract passages.
3. If backend LLM settings are configured, Chronicle can propose passage-linked claims and an evidence-bounded synthesis draft.
4. Review claims and evidence relationships, recording whether each edge is human-reviewed or model-inferred.
5. Inspect the persisted evidence graph and record source correction/retraction events.
6. Chronicle traverses stored source/claim dependencies and flags impacted claims and report versions for review.
7. Export a Markdown or JSON Evidence Passport with a snapshot of source records, exact passages, relationships, events and report history.

Retrieved abstracts are not full-text appraisal. Generated candidates remain unreviewed; the system does not claim calibrated scientific truth, exhaustive coverage, or global novelty.

## Repository
```
apps/web/                 Next.js + TypeScript workspace UI
services/api/             FastAPI API, ORM, retrieval and evidence services
services/api/migrations/  Alembic schema migration
docs/                     Architecture, roadmap and implementation status
infra/docker-compose.yml  Full local stack: PostgreSQL, API and web
.github/workflows/        API tests and web lint/typecheck/build
```

## Run the full stack with Docker
Prerequisites: Docker Desktop / Docker Compose.

```bash
docker compose -f infra/docker-compose.yml up --build
```

Open:
- Web workspace: http://localhost:3000
- API documentation: http://localhost:8000/docs
- API health: http://localhost:8000/api/v1/health

The default database password is for local development only. Set a different `POSTGRES_PASSWORD` in your local environment for non-local environments. Uploaded PDFs are stored in a local Docker volume; configure access-controlled object storage before deployment.

## Run services manually
### API
```bash
cd services/api
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set DATABASE_URL and other settings; see services/api/.env.example
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Web
```bash
corepack enable
pnpm install
pnpm --filter @chronicle/web dev
```
Set `NEXT_PUBLIC_API_BASE_URL` in `apps/web/.env.local` when the API is not at `http://localhost:8000`.

## Optional model-backed synthesis
The API supports an OpenAI-compatible chat-completions endpoint. Configure these variables **only on the backend**:
- `OPENAI_API_KEY`
- `OPENAI_API_BASE` (defaults to the OpenAI API base URL)
- `OPENAI_MODEL`

When credentials/model are not configured, the discovery run still performs academic metadata retrieval and saves a discovery snapshot. Do not expose provider keys in `NEXT_PUBLIC_*` variables or commit them.

## Main endpoints
- `POST /api/v1/projects`, `GET /api/v1/projects`
- `POST /api/v1/research/runs`, `GET /api/v1/research/runs`, `GET /api/v1/research/runs/{run_id}`
- `GET /api/v1/sources/search?q=...` — Crossref/OpenAlex metadata search
- `POST /api/v1/sources/papers`, `GET /api/v1/sources/papers`
- `POST /api/v1/documents/upload`, `GET /api/v1/documents/papers/{paper_id}/passages`
- `POST /api/v1/evidence/claims`, `POST /api/v1/evidence/claims/{claim_id}/relations`
- `PATCH /api/v1/evidence/relations/{relation_id}/review`
- `POST /api/v1/evidence/paper-dependencies`
- `GET /api/v1/evidence/runs/{run_id}/graph`
- `GET /api/v1/sources/papers/{paper_id}/status-check` — status-signal preview; no event is recorded automatically
- `POST /api/v1/sources/papers/{paper_id}/events`, `GET /api/v1/sources/events`
- `POST /api/v1/evidence/runs/{run_id}/reports`, `GET /api/v1/evidence/runs/{run_id}/reports`
- `GET /api/v1/evidence/runs/{run_id}/passport?format=markdown|json`

## Validation
API tests use an isolated SQLite database and mock scholarly providers for deterministic pipeline tests:
```bash
cd services/api
pytest -q
```
GitHub Actions also runs API tests and frontend lint, type checking and a production build.

## Principles
- An evidence edge is labelled by provenance basis: source-documented, metadata-derived, model-inferred or human-reviewed.
- A support label is not a universal truth score.
- Source corrections/retractions trigger downstream review, not automatic invalidation.
- Graph gaps are not proof of nonexistence.
- Keep implemented, simulated and planned capabilities clearly separated.
