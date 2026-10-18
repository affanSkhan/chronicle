# Chronicle
### Temporal Evidence Intelligence for Scientific Research

Chronicle is a research assistant designed to connect research claims to their supporting evidence, model source dependencies, track publication-status changes, and explain which conclusions may need reassessment when evidence changes.

> **Project status:** Foundation / initial scaffold. Modules are being implemented incrementally. Features described as planned are not yet implemented.

## Vision
Chronicle extends a conventional research workflow with a versioned claim–evidence graph:
- Academic source discovery and PDF ingestion
- Exact passage-level evidence and citation verification
- Source provenance and dependency indicators
- Context-aware support, contradiction, qualification, and non-comparability assessment
- Versioned research reports and source-update impact analysis
- An inspectable Evidence Trace and exportable Evidence Passport

The research contribution will be assessed experimentally; novelty and performance improvements are not assumed in advance.

## Repository layout
```
chronicle/
  apps/
    web/             # Next.js + TypeScript frontend
  services/
    api/             # FastAPI backend
  packages/
    contracts/       # Shared API/schema documentation
  docs/
    architecture.md
    roadmap.md
    decisions/
  infra/
    docker-compose.yml
  .github/workflows/
```

## Development status
The repository is being bootstrapped. See [docs/roadmap.md](docs/roadmap.md) for the planned milestones and [docs/architecture.md](docs/architecture.md) for the initial system design.

## Planned stack
- **Frontend:** Next.js, React, TypeScript, Tailwind CSS
- **Backend:** Python, FastAPI, Pydantic
- **Persistence:** PostgreSQL; pgvector can be enabled when semantic retrieval is added
- **Graph processing:** NetworkX for the prototype, with durable graph relationships stored in PostgreSQL
- **Local services:** Docker Compose
- **Testing:** Pytest and frontend unit/e2e testing as modules arrive

## Quick start
Prerequisites: Node.js LTS, pnpm, Python 3.11+, and Docker (recommended).

The initial scaffold is being added in stages. Follow each app's README for setup as it becomes available.

## Engineering principles
1. Every material claim should be traceable to an evidence record or explicitly marked unsupported.
2. Keep model-inferred relationships separate from source-documented facts.
3. A retraction or correction triggers impact analysis, not automatic rejection of all dependent claims.
4. Preserve report versions and record why assessments changed.
5. Never expose API keys in the frontend or commit them to the repository.
6. Distinguish implemented, simulated, and planned capabilities in the UI and documentation.

## Project
Final-year B.Tech Computer Engineering major project, VIIT Pune.
