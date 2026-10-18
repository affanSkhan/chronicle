# Chronicle
### Temporal Evidence Intelligence for Scientific Research

Chronicle is a research assistant designed to connect research claims to evidence, model source dependencies, track publication-status changes, and explain which conclusions may need reassessment when evidence changes.

> **Project status:** Early scaffold. The initial UI uses illustrative demo records, and the initial API stores runs in memory. Academic retrieval, real evidence verification, persistent database storage, and temporal monitoring are not implemented yet.

## Vision
- Academic source discovery and PDF ingestion
- Exact passage-level evidence and citation verification
- Source provenance and dependency indicators
- Context-aware support, contradiction, qualification and comparability assessment
- Versioned reports and source-update impact analysis
- An inspectable Evidence Trace and exportable Evidence Passport

The research contribution will be assessed experimentally; novelty and performance improvements are not assumed in advance.

## Repository layout
```
apps/web/                 Next.js + TypeScript workspace UI
services/api/             FastAPI API
docs/                     Architecture, roadmap and decision records
infra/docker-compose.yml  Local PostgreSQL
.github/workflows/        CI checks
```

## Stack
- Frontend: Next.js, React, TypeScript, Tailwind CSS
- Backend: Python, FastAPI, Pydantic
- Persistence target: PostgreSQL; pgvector when semantic retrieval is introduced
- Graph algorithms: NetworkX initially
- Local services: Docker Compose

## Run the API
```bash
cd services/api
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
API docs: http://localhost:8000/docs

## Run the web application
```bash
corepack enable
pnpm install
pnpm --filter @chronicle/web dev
```
Open http://localhost:3000. Set `NEXT_PUBLIC_API_BASE_URL` in `apps/web/.env.local` if the API is not at http://localhost:8000.

## Local database
```bash
docker compose -f infra/docker-compose.yml up -d
```
Database persistence is planned but not wired into the API yet. The current in-memory research-run store resets on restart.

## Engineering principles
1. Every material claim should trace to an evidence record or be explicitly marked unsupported.
2. Distinguish documented facts from inferred relationships.
3. A retraction or correction triggers impact analysis, not automatic rejection of all dependent claims.
4. Preserve report versions and record why assessments changed.
5. Keep provider API keys server-side.
6. Distinguish implemented, simulated, and planned capabilities.
