# Chronicle API

FastAPI service. Initial API exposes a root status endpoint and `/api/v1/health`; domain modules will be added incrementally.

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

Configuration is read from environment variables. Never commit real secrets.
