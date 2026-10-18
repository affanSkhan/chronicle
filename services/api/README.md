# Chronicle API

FastAPI service for research projects/runs, scholarly metadata discovery, PDF ingestion, evidence modelling, report versioning and temporal source-event impact analysis.

## Recommended: run the full stack
From the repository root:
```bash
docker compose -f infra/docker-compose.yml up --build
```
Web: http://localhost:3000 · API docs: http://localhost:8000/docs

## Run API directly
```bash
cd services/api
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Copy .env.example to .env; set DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

## Main endpoints
- `GET /api/v1/health` — process liveness.
- `POST /api/v1/projects`, `GET /api/v1/projects` — research project records.
- `POST /api/v1/research/runs` with `execute=true` — trigger live scholarly metadata discovery.
- `GET /api/v1/sources/search?q=...&provider=all` — Crossref/OpenAlex metadata search.
- `POST /api/v1/sources/papers` — import bibliographic metadata.
- `POST /api/v1/documents/upload` — extract selectable PDF text into page-aware passages.
- `POST /api/v1/evidence/claims` — create a claim record.
- `POST /api/v1/evidence/claims/{claim_id}/relations` — attach a passage or claim relationship with provenance/review labels.
- `PATCH /api/v1/evidence/relations/{relation_id}/review` — record human review.
- `POST /api/v1/evidence/paper-dependencies` — record source dependence.
- `GET /api/v1/evidence/runs/{run_id}/graph` — persisted graph.
- `GET /api/v1/sources/papers/{paper_id}/status-check` — read-only Crossref/OpenAlex status preview.
- `POST /api/v1/sources/papers/{paper_id}/status-check` — persist a manual status check and compare signal fingerprints.
- `PATCH /api/v1/sources/papers/{paper_id}/monitoring` — enable/disable scheduled checks and configure interval.
- `GET /api/v1/sources/status-checks` and `GET /api/v1/sources/papers/{paper_id}/status-checks` — view persisted check history.
- `POST /api/v1/sources/papers/{paper_id}/events` — record an event and trigger impact review.
- `GET /api/v1/evidence/runs/{run_id}/reports` — report history.
- `GET /api/v1/evidence/runs/{run_id}/passport?format=markdown|json` — Evidence Passport export.

## Scheduled source monitoring
Direct API runs leave the scheduler disabled by default. Set `ENABLE_SCHEDULED_MONITORING=true` to start the in-process poller, with `SOURCE_MONITOR_POLL_SECONDS` and `SOURCE_MONITOR_BATCH_SIZE` controlling the loop. The local Docker Compose configuration enables it by default. The current poller is single-process; do not enable it on multiple API replicas until a distributed worker/leader lock is implemented. It persists metadata signals and change hashes but never auto-marks a paper retracted or creates a SourceEvent.

## Optional LLM configuration
Set `OPENAI_API_KEY`, `OPENAI_API_BASE`, and `OPENAI_MODEL` on the backend only. With no configured key/model, discovery still retrieves metadata and abstract passages and saves a report without model-generated claims or synthesis.

## Limitations
Crossref/OpenAlex records are not a complete index of all research, and abstract-level evidence is not full-text verification. Source status checks are not scheduled continuous monitoring. LLM-generated claims and research-question suggestions remain unreviewed candidates. PDF uploads are stored in local/container storage; use authenticated durable object storage before public deployment.

## Tests
```bash
pytest -q
```
API tests use an isolated SQLite database and deterministic provider fixtures.
