# Chronicle — Initial Architecture

## Goals
Chronicle aims to produce research outputs with inspectable claim provenance, preserve research state over time, and reassess claims when source evidence changes.

## Components
1. **Web workspace** — query submission, job status, reports, evidence ledger, provenance graph, report comparison.
2. **API service** — validation, orchestration endpoints, persistence and source connectors.
3. **Research orchestration** — bounded workflows. Agents work on shared state; they are not independent sources of truth.
4. **Evidence model** — papers, versions, studies, passages, claims, relationships, source events and report snapshots.
5. **Temporal impact engine** — traverses dependencies from changed sources to claims/conclusions requiring review.
6. **Evaluation suite** — deterministic tests and labelled cases for retrieval, support, dependency links and update propagation.

## Claim/evidence lifecycle
Question -> Search -> Paper/Version -> Passage -> Evidence -> Claim -> Assessment -> Report Version
                                                                                   ^
Source event (correction/retraction/new version) -> Impact analysis -> reassessment

## Design rules
- Use stable internal IDs and retain DOI/source identifiers.
- Store exact evidence passages with page/section and source-version references.
- Record relationship basis: source-documented, metadata-derived, model-inferred, or human-reviewed.
- Validate model outputs with schemas, source pointers and deterministic checks.
- Do not treat paper counts as independent-evidence counts.
- A missing graph edge is not proof a relationship does not exist.
- A source-status event triggers reassessment; it does not automatically invalidate downstream claims.
- Keep provider API keys server-side and redact secrets from logs.

## Initial entities
ResearchProject, ResearchRun, Paper, PaperVersion, Study, Passage, Claim, EvidenceRelation, SourceEvent and ReportVersion.

## API approach
FastAPI exposes JSON endpoints under the API v1 prefix. Long research tasks use a run/job model instead of holding a browser request open.

## First implementation slice
Establish app shells, health checks, environment configuration, error contracts, database-ready services, local compose infrastructure and CI. Academic integrations and LLM orchestration come later behind provider interfaces.
