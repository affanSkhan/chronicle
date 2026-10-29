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
- `GET /api/v1/sources/search?q=...&provider=all` — Crossref/OpenAlex/Semantic Scholar plus public-web discovery snippets.
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
Direct API runs leave the scheduler disabled by default. Set `ENABLE_SCHEDULED_MONITORING=true` to start the in-process poller, with `SOURCE_MONITOR_POLL_SECONDS` and `SOURCE_MONITOR_BATCH_SIZE` controlling the loop. Local Docker Compose enables it by default. This poller is single-process; do not enable it on multiple API replicas until a distributed worker/leader lock is implemented.

For free hosted environments that sleep, `.github/workflows/source-monitor.yml` runs the due-check script hourly when the repository secret `CHRONICLE_DATABASE_URL` is configured. See [docs/deployment-free-tier.md](../../docs/deployment-free-tier.md). Both approaches persist metadata signals and change hashes but never auto-mark a paper retracted or create a SourceEvent.

## Uploaded PDFs, privacy, and retrieval

Chronicle validates PDF type/signature, byte size, and page count, extracts page-aware passages, and uses selected passage excerpts in a research run when the owner attaches a PDF. The runner first ranks passages with deterministic BM25 lexical retrieval; if a Hugging Face token is configured, it embeds a bounded lexical shortlist with `BAAI/bge-small-en-v1.5` and combines dense and lexical ranks with reciprocal rank fusion (RRF). This is a retrieval ranking, not a calibrated evidence score. Without `HF_TOKEN`, the workflow remains usable in BM25-only mode; if inference fails, it falls back to BM25 and records the fallback in the run snapshot. Hugging Face Inference Providers offers a feature-extraction API for embedding use cases, subject to provider/model availability and quota: https://huggingface.co/docs/inference-providers/en/tasks/feature-extraction

The original PDF bytes can be written to a private S3-compatible bucket by configuring `OBJECT_STORAGE_ENDPOINT_URL`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY_ID`, `OBJECT_STORAGE_SECRET_ACCESS_KEY`, and optionally `OBJECT_STORAGE_REGION` / `OBJECT_STORAGE_PREFIX`. Never commit these credentials. On production/serverless deployments without a complete object-store configuration, Chronicle writes the original bytes to the separate `uploaded_pdf_blobs` PostgreSQL table created by migration 0008; the metadata table does not load binary content on ordinary reads. Vercel requests are capped at 3 MB until direct-to-object-storage uploads are implemented. Ensure `alembic upgrade head` has run before using this fallback. See https://vercel.com/docs/functions/limitations.

Owners may permanently delete an uploaded PDF via `DELETE /api/v1/documents/papers/{paper_id}`. This removes the stored object when the storage backend is configured/reachable, extracted passages, linked and dependent claims, source status/event records and source dependency edges; affected report versions are redacted, and potentially sensitive audit payloads are redacted while retaining the audit record of deletion. This is an application-level deletion operation, not proof that backups or provider-side logs are erased.

## Scholarly-provider authentication

OpenAlex permits limited anonymous querying, but configure a free `OPENALEX_API_KEY` for dependable production discovery and source-status checks. Create the key at [OpenAlex Settings → API key](https://openalex.org/settings/api) and store it only in the API service's environment. Chronicle sends it as a Bearer token only to OpenAlex; it is not sent to Crossref or exposed in query URLs. Without a key, the Crossref provider remains available and OpenAlex may return fewer results or become unavailable.

## Zero-cost LLM configuration

Set these server-side variables to use Groq's free tier:
- `LLM_API_KEY`: key from https://console.groq.com/keys
- `LLM_API_BASE=https://api.groq.com/openai/v1`
- `LLM_MODEL=openai/gpt-oss-20b`

The free plan has token and request caps, so the implementation uses bounded passages and response tokens. No paid credits or billing method are required for this configuration. If the free provider is unavailable or rate-limited, retrieval-only research and exports remain available. Legacy `OPENAI_*` settings are still supported; OpenAI API billing is separate from ChatGPT.

## Limitations
Crossref/OpenAlex/Semantic Scholar records are not a complete index of all research. Public-web results are title/snippet discovery leads, not verified full-text evidence; abstract-level evidence is not full-text verification. Source monitoring is not exhaustive publisher surveillance. LLM-generated claims and research-question suggestions remain unreviewed candidates. The optional database-backed run queue requires a continuously running worker; it is not enabled on Vercel by default.

## Tests
```bash
pytest -q
```
API tests use an isolated SQLite database and deterministic provider fixtures.


## FF180 completion-branch regression coverage

The completion branch adds tests for BM25 determinism, optional dense-embedding/RRF ranking and provider-failure fallback, cross-provider search-rank fusion, uploaded-PDF passage selection inside a real research run, cross-account attachment denial, private object-storage behavior, and owner-scoped permanent deletion/report redaction. Run the full API suite with:

```bash
cd services/api
pytest -q
```

These tests validate code paths and data-integrity behavior. They are not scientific-accuracy results: benchmark metrics must be computed from a frozen, labelled evaluation set as described in [the evaluation protocol](../../docs/evaluation-protocol.md).


## Optional durable research queue worker

The default `RESEARCH_EXECUTION_MODE=inline` keeps local development and serverless behavior compatible. To use a persistent PostgreSQL queue with a separate worker, set `RESEARCH_EXECUTION_MODE=queue` in the root `.env`, then apply the latest database migrations and start the worker profile:

```bash
docker compose -f infra/docker-compose.yml --profile worker up --build
```

The API persists queued runs; the worker claims them transactionally, writes audit events and heartbeats, and marks stale worker leases failed for explicit retry instead of silently rerunning partially completed work. This does not provide checkpoint-level resume, and it is not a hosted worker deployment by itself. Keep queue mode disabled unless a worker is actually running.
