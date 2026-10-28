# Chronicle implementation status

Last reviewed: 2026-10-29  
Repository: [affanSkhan/chronicle](https://github.com/affanSkhan/chronicle)  
Completion branch: `feat/ff180-completion-pass`  
Approved basis: VIIT FF180 synopsis for “Multi-Agent Research Assistant with Explainable Reasoning”.

This is an implementation audit, not a claim of full SRS compliance. The completion branch is separate from `main`; its new functionality must pass branch-head CI, be reviewed/merged, and be verified after deployment before it can be described as production functionality.

## Implemented in the current repository

- **Identity and workspace security:** Argon2 password hashes, signed bearer tokens, owner-scoped workspace/run/source/evidence queries, archive/restore, and audit events for material operations.
- **Scholarly retrieval:** Crossref and OpenAlex adapters, DOI/title normalization and deduplication, provider rank fusion, and reciprocal-rank fusion across planned subqueries. Coverage limitations and provider errors are preserved rather than hidden.
- **Four execution modes:** Quick Discovery, Deep Research, Academic Review, and Forensic Analysis have bounded, mode-specific query plans and stage policies. The planner is deterministic; it is not the full autonomous multi-agent/LangGraph architecture in the synopsis.
- **PDF ingestion:** PDF content-type/signature, byte and page limits, PyMuPDF extraction, bounded Tesseract OCR for low-text pages, passage/page metadata, SHA-256 duplicate detection, and per-file extraction/coverage warnings. OCR behavior is tested with mocks; real-scan accuracy is not measured.
- **PDF-to-run evidence path (completion branch):** A run can attach up to five PDFs owned by the authenticated user. The pipeline loads saved page-aware passages and ranks them with BM25. When `HF_TOKEN` is configured, it reranks a bounded lexical shortlist using Hugging Face feature-extraction embeddings and reciprocal-rank fusion. If the token is absent or the service fails, the run falls back to BM25 and records that state. Retrieval scores are not confidence scores; dense embeddings are calculated per run and are not persistently indexed.
- **Claim extraction and verification:** Optional configured LLM stages produce schema-validated claim/synthesis candidates with passage IDs. A separate verifier supports supported, partially supported, contradicted, insufficient-evidence, and unverifiable labels. Invalid passage pointers are discarded or downgraded; generated judgments remain review prompts, not scientific truth.
- **Evidence graph and review:** Persisted sources, versions, passages, studies, claims, report versions, typed relations, review transitions, and audit metadata; graph output also exposes report conclusions and recommendations from saved synthesis. Human acceptance/rejection actions are available.
- **Dependency candidates:** Recognized dataset/study-registry identifiers and high-overlap abstracts produce review-only candidate links. Confirmed relationships can affect temporal impact traversal. This is a limited heuristic detector, not generalized citation ancestry or proof of study independence.
- **Temporal records and targeted reassessment:** Crossref/OpenAlex status checks, manually recorded source events, dependency traversal, impacted claim/report review flags, and preserved report versions. A researcher can request owner-scoped, bounded re-verification of affected claims; model verdicts are audit-logged and remain flagged for human review. Scheduled signals still do not automatically become authoritative events, and queued/background reassessment after detected updates is not implemented.
- **Report lifecycle and exports:** Report version history, parent links, change summaries, Markdown, JSON, and PDF Evidence Passport exports with source/passage/claim/dependency/event/audit snapshots.
- **Permanent uploaded-PDF deletion (completion branch):** Owner-scoped delete endpoint removes original bytes when the configured storage backend can do so, deletes passages and claims derived from those passages plus dependent claim records, removes source dependency/status/event/study records, and redacts impacted report versions and sensitive audit payloads. This is application-level deletion; backups and third-party retention are not purged by this endpoint.
- **UI improvements (completion branch):** PDF picker with a five-file limit, clear lexical/dense retrieval disclosure, private storage durability warning, and an irreversible-delete dialog explaining which dependent records are removed/redacted.
- **Testing and local deployment:** API unit/integration tests, SQLite migration tests, Next.js typecheck/lint/build, container validation/build, Docker Compose, Alembic, example environment files, GitHub Actions CI, and an evaluation metrics/protocol harness.

## Still partial or not implemented

- **Production document storage requires explicit verification.** The currently visible Vercel API environment variables do not include an OBJECT_STORAGE configuration; until a private object store is configured and upload/read/delete is tested in production, uploaded originals may rely on ephemeral filesystem storage. Do not describe these originals as durable.

1. **Not yet a complete multi-agent system.** The executed flow is a bounded deterministic pipeline with modular model stages, not the full seven/eight-layer autonomous orchestrator described by the proposal.
2. **Not a full-text systematic-review system.** External search returns metadata and abstracts; user-selected PDFs contribute retrieved excerpts. Publisher full-text acquisition, supplementary-material handling, document-wide critical appraisal, and exhaustive academic/web-provider coverage are not implemented.
3. **Hybrid retrieval has limits.** Dense reranking is optional, requires `HF_TOKEN`, and considers a bounded BM25 shortlist to control inference usage. It does not guarantee semantic recall over every passage. Retrieval vectors are not stored in pgvector or persistently indexed. Without a token, BM25-only behavior is intentional.
4. **Durable background jobs are missing.** Run processing still uses FastAPI in-process background tasks; restart-safe recovery, persisted subtask checkpoints, distributed cancellation and a durable worker queue are not implemented.
5. **Original-file storage requires configuration.** The branch includes an S3-compatible private storage adapter, but durable originals work only when all `OBJECT_STORAGE_*` variables point to a private bucket and are verified. The fallback on Vercel is ephemeral. Direct-to-object-storage browser uploads for files larger than Vercel's 4.5 MB function request limit are not implemented; set a conservative API limit such as 3 MB on Vercel until that flow exists.
6. **Retention is incomplete.** Permanent deletion redacts application records, but there is no policy-driven retention schedule, backup-expiry confirmation, or proof of provider-side erasure.
7. **Temporal reassessment is human-led.** Changes flag affected claims/reports and reviewers can invoke the citation verifier. An automatic queued reverification job and comprehensive claim-by-claim before/after diff are missing.
8. **Production operations require further work.** Rate limiting/abuse controls, comprehensive alerts/monitoring, backup/restore drills, a full route-by-route security review and a durable worker design are not complete. Live browser acceptance against production remains required.
9. **Research evaluation remains unmeasured.** No reproducible, labelled held-out results have been recorded for SciFact/SciFact-Open, ALCE-style citation quality, relation-class F1, dependency precision/recall, temporal-impact precision/recall/false alarms, or configurations A–D. Metrics code and an evaluation protocol are not experimental results.
10. **No efficacy claims are justified by unit tests.** Tests prove software-path behavior and regression protection; they do not establish that model judgments, dependency signals, or temporal-impact predictions are scientifically accurate.

## Configuration needed for the optional features

- **Dense passage reranking:** `HF_TOKEN`, `HF_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, and `HF_EMBEDDING_API_BASE=https://router.huggingface.co/hf-inference/models`. Hugging Face provider/model availability and quotas apply. Without this, BM25 works without an embedding provider.
- **Durable original PDF bytes:** `OBJECT_STORAGE_ENDPOINT_URL`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY_ID`, and `OBJECT_STORAGE_SECRET_ACCESS_KEY` are all required; region and prefix may also be configured. Credentials must stay in the API's server-side environment.
- **Model-assisted extraction/synthesis and citation verifier:** a server-side supported `LLM_API_KEY` / `LLM_MODEL` configuration (or supported legacy OpenAI setting) is required. Without it, retrieval-only workflows remain possible and reports should disclose the missing stage.

## Deployment and release status

The current FF180 completion changes are on `feat/ff180-completion-pass`, not yet merged into `main`. The branch introduces no database schema migration; the latest lifecycle migration in the repository is `0007_run_cancel_retry`. Before release, require the API, web and container checks to pass on the exact branch head, review the PR, merge, and verify both Git-integrated Vercel production deployments are READY on the merge SHA. Then run the production smoke suite described in [`docs/deployment-vercel.md`](deployment-vercel.md). Do not call dense embeddings or durable PDF storage enabled until the corresponding Vercel environment variables are verified.

## Relevant references

- [SRS traceability matrix](srs-traceability.md)
- [Evaluation protocol](evaluation-protocol.md)
- [Vercel deployment and acceptance checklist](deployment-vercel.md)
- [API README](../services/api/README.md)
