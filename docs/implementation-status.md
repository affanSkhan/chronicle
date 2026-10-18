# Implementation status (2026-10-18)

## Implemented in repository
- Project README, architecture, roadmap and initial stack decision record.
- Next.js/React/TypeScript workspace prototype with overview, research workspace, illustrative evidence graph, source timeline and hypothesis-lab views.
- FastAPI application with health endpoint.
- Initial POST/list/get research-run endpoints backed by an in-memory dictionary.
- Pydantic request/response models and API tests.
- Local PostgreSQL Docker Compose configuration (the API is not connected to it yet).
- API CI workflow.

## Explicitly not implemented yet
- External web/academic search.
- PDF uploads/text extraction.
- Live citation or claim verification.
- PostgreSQL persistence or migrations.
- Evidence graph persistence and graph computation.
- LLM calls or real agent orchestration.
- Source correction/retraction polling.
- Temporal impact propagation.
- Authentication and multi-user access.
- Report export / Evidence Passport.

All sample claims and graph edges in the frontend are illustrative and must not be interpreted as actual research findings.
