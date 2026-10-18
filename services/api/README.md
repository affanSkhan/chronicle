# Chronicle API

FastAPI service exposing the initial research-run API. The current run store is in memory and **demo-only**. It will be replaced with PostgreSQL persistence in the next milestone.

## Local run
```bash
cd services/api
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Swagger UI: http://localhost:8000/docs

## Initial endpoints
- `GET /` — service status
- `GET /api/v1/health` — liveness check
- `POST /api/v1/research/runs` — create a demo run request
- `GET /api/v1/research/runs` — list in-memory demo requests
- `GET /api/v1/research/runs/{run_id}` — retrieve a demo request

No web or academic search is executed yet. Configuration is read from environment variables. Never commit real secrets.
