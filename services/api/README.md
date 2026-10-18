# Chronicle API

FastAPI service providing persistent project/run APIs, scholarly metadata search, PDF ingestion, claim/evidence APIs, dependency graph records and manual temporal source-event handling.

## Local run
1. Start PostgreSQL from the repository root:

       docker compose -f infra/docker-compose.yml up -d

2. Create an environment and install dependencies:

       cd services/api
       python -m venv .venv
       # Windows PowerShell: .\.venv\Scripts\Activate.ps1
       # macOS/Linux: source .venv/bin/activate
       pip install -r requirements.txt

3. Copy .env.example to .env, then apply schema:

       alembic upgrade head

4. Start the service:

       uvicorn app.main:app --reload --port 8000

API docs: http://localhost:8000/docs

## Main endpoints
- GET /api/v1/health — process liveness.
- POST /api/v1/projects and GET /api/v1/projects — project records.
- POST /api/v1/research/runs and GET /api/v1/research/runs — persistent research requests. Current runs are explicitly demo-only; no research worker executes them yet.
- GET /api/v1/sources/search?q=...&provider=all — Crossref/OpenAlex metadata discovery.
- POST /api/v1/sources/papers — import metadata into the library.
- POST /api/v1/documents/upload — extract selectable PDF text into page-aware passages.
- GET /api/v1/documents/papers/{paper_id}/passages — inspect extracted passages.
- POST /api/v1/evidence/claims — create an atomic claim for a research run.
- POST /api/v1/evidence/claims/{claim_id}/relations — attach a passage or related claim with relation/provenance/review labels.
- POST /api/v1/evidence/paper-dependencies — record a source-dependency relationship.
- GET /api/v1/evidence/runs/{run_id}/graph — retrieve persisted graph nodes and edges.
- POST /api/v1/evidence/runs/{run_id}/reports and GET — persist report versions.
- POST /api/v1/sources/papers/{paper_id}/events — record a source event and flag affected claims/report versions for review.

## Provider and file limitations
- Crossref/OpenAlex results are bibliographic metadata, not verified claim evidence.
- PDF extraction handles selectable text only. Scanned documents need OCR, which is not enabled.
- PDF files are stored locally under UPLOAD_DIR; configure durable/private object storage before deployment.
- API keys for any later LLM providers must stay in the backend environment and must never use a NEXT_PUBLIC_ variable.

## Tests
Run from this directory:

       pytest -q

Tests use isolated SQLite and do not need a live PostgreSQL instance or internet access.
