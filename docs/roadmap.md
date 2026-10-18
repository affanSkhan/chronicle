# Chronicle implementation roadmap

## Milestone 0 — Foundation
- [x] Repository vision and initial structure
- [ ] Frontend shell and design system
- [ ] FastAPI app, health endpoint and settings
- [ ] Docker Compose with PostgreSQL
- [ ] CI and tests
- [ ] API schemas and error contract
- [ ] Environment/secret handling

## Milestone 1 — Research workspace MVP
- Project creation and research question submission
- Research-run lifecycle (queued/running/completed/failed)
- Clearly labelled demo data
- Responsive workspace, report and evidence panels
- Persistent project and run records

## Milestone 2 — Source discovery and ingestion
- Crossref/OpenAlex provider abstraction
- Search history and source provenance
- PDF upload with file/type/size validation
- PDF text extraction and passage segmentation
- DOI normalization and duplicate detection

## Milestone 3 — Evidence model
- Atomic claim and evidence schemas
- Claim-to-passage verification
- Support / contradict / qualify / not-comparable / insufficient-evidence
- Evidence ledger and graph view
- Explicit versus inferred provenance

## Milestone 4 — Dependency-aware synthesis
- Citation ancestry and metadata relationships
- Evidence dependency clusters and explanations
- Independence profile, not a misleading truth score
- Human review and correction

## Milestone 5 — Temporal evidence lifecycle
- Correction, retraction, new-version and metadata-change events
- Scheduled source-status checks
- Affected-claim traversal
- Versioned report snapshots and diffs
- Preserve old versions; reassess rather than auto-invalidate

## Milestone 6 — Hypothesis Lab and evaluation
- Evidence-grounded opportunity cards
- Prior-art search and human validation
- Benchmark fixtures and ablation experiments
- Cost, latency, precision/recall and impact-analysis evaluation

## Release gates
A feature is complete only when it has typed contracts, unit tests, loading/empty/error states, provenance/limitations disclosure and a documented acceptance test.
