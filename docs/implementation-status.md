# Chronicle implementation status

Last reviewed: 2026-10-29  
Repository: [affanSkhan/chronicle](https://github.com/affanSkhan/chronicle)  
Hardening branch: `feat/ff180-final-hardening`  
Approved basis: VIIT FF180 synopsis for “Multi-Agent Research Assistant with Explainable Reasoning”.

This is an implementation audit, not a claim of full SRS compliance. The core FF180 completion work was merged into `main` at `5223600e722fe53e8b6a950879a7720b484911b7`. The final hardening branch adds provider, storage, LangGraph planning, queue and evaluation infrastructure. It is not production functionality until reviewed, merged, migrated and verified against the deployed commit.

## Implemented in the current repository

- **Identity and workspace security:** Argon2 password hashes, signed bearer tokens, owner-scoped workspace/run/source/evidence queries, archive/restore, and audit events for material operations.
- **Scholarly retrieval:** Crossref, OpenAlex, and Semantic Scholar adapters with DOI/title normalization, provider rank fusion, and reciprocal-rank fusion across planned subqueries. An additional public-web adapter returns attributed result URLs and short discovery snippets. Web snippets are explicitly distinguished from article abstracts/full text. Coverage limitations and provider errors are preserved rather than hidden.
- **Four execution modes and bounded LangGraph planning:** Quick Discovery, Deep Research, Academic Review, and Forensic Analysis retain bounded, mode-specific stage policies. In non-quick modes, a LangGraph query-planner node may propose subqueries and a critic node validates query bounds and safety; no configured model or planner failure falls back to a deterministic plan. This is not yet the complete specialized, iterative multi-agent architecture in the synopsis.
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

- **Production document storage requires migration 0008 and live verification.** The hardening branch adds a separate PostgreSQL `uploaded_pdf_blobs` table for original-PDF bytes when private object storage is not configured; serverless uploads are capped at 3 MB. Read-only inspection of the connected Neon database on 2026-10-29 showed the new table was absent. Apply migration 0008 through the reviewed migration workflow, then test upload/read/delete against the exact deployed commit.

1. **Multi-agent orchestration remains partial.** A two-node LangGraph query-planner/critic graph is implemented with deterministic fallback, but specialized agents for discovery, study appraisal, claim verification, synthesis and temporal monitoring are not independently orchestrated, and the retrieval loop does not yet iterate from evidence gaps.
2. **Not a full-text systematic-review system.** External search returns metadata and abstracts; user-selected PDFs contribute retrieved excerpts. Publisher full-text acquisition, supplementary-material handling, document-wide critical appraisal, and exhaustive academic/web-provider coverage are not implemented.
3. **Hybrid retrieval has limits.** Dense reranking is optional, requires `HF_TOKEN`, and considers a bounded BM25 shortlist to control inference usage. It does not guarantee semantic recall over every passage. Retrieval vectors are not stored in pgvector or persistently indexed. Without a token, BM25-only behavior is intentional.
4. **Durable background execution is opt-in, not deployed.** The API can persist a PostgreSQL-backed queue and a separate Docker worker can claim runs with heartbeats/stale-lease handling. Vercel is still in inline mode because no separate always-on worker is deployed. Checkpoint-level resume, distributed cancellation and subtask-level progress remain incomplete.
5. **Original-file storage supports two durable backends.** A configured private S3-compatible bucket is preferred; after migration 0008, production/serverless can fall back to the separate PostgreSQL blob table. The serverless request limit is conservatively capped at 3 MB until direct-to-object-storage uploads are implemented. Live DB migration and upload/read/delete acceptance are still required.
6. **Retention is incomplete.** Permanent deletion redacts application records, but there is no policy-driven retention schedule, backup-expiry confirmation, or proof of provider-side erasure.
7. **Temporal reassessment is human-led.** Changes flag affected claims/reports and reviewers can invoke the citation verifier. An automatic queued reverification job and comprehensive claim-by-claim before/after diff are missing.
8. **Production operations require further work.** Rate limiting/abuse controls, comprehensive alerts/monitoring, backup/restore drills, a full route-by-route security review and a durable worker design are not complete. Live browser acceptance against production remains required.
9. **Research evaluation remains unmeasured.** No reproducible, labelled held-out results have been recorded for SciFact/SciFact-Open, ALCE-style citation quality, relation-class F1, dependency precision/recall, temporal-impact precision/recall/false alarms, or configurations A–D. Metrics code and an evaluation protocol are not experimental results.
10. **No efficacy claims are justified by unit tests.** Tests prove software-path behavior and regression protection; they do not establish that model judgments, dependency signals, or temporal-impact predictions are scientifically accurate.

## Configuration needed for the optional features

- **Dense passage reranking:** `HF_TOKEN`, `HF_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, and `HF_EMBEDDING_API_BASE=https://router.huggingface.co/hf-inference/models`. Hugging Face provider/model availability and quotas apply. Without this, BM25 works without an embedding provider.
- **Durable original PDF bytes:** Configure all `OBJECT_STORAGE_ENDPOINT_URL`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY_ID`, and `OBJECT_STORAGE_SECRET_ACCESS_KEY` to use private object storage. Alternatively, after migration 0008, serverless deployments use the private PostgreSQL blob table with a 3 MB upload cap. Credentials must stay server-side.
- **Model-assisted extraction/synthesis and citation verifier:** a server-side supported `LLM_API_KEY` / `LLM_MODEL` configuration (or supported legacy OpenAI setting) is required. Without it, retrieval-only workflows remain possible and reports should disclose the missing stage.

## Deployment and release status

The hardening work is on `feat/ff180-final-hardening` and is pending integration. API and Container CI passed on commit `8a9e98d1a465746de28a230e09792f2726c87212`; subsequent changes must be re-tested on the final PR head. Migration 0008 is required for the PostgreSQL PDF fallback and is not yet applied to the connected production database. The previously inspected Vercel production deployments lag the merged main commit; Vercel returned build-rate-limit failures and denied direct production deployment requests. No production rollout or browser acceptance is claimed. Before release, merge the reviewed PR, apply migration 0008 through the repository workflow, resolve Vercel deployment authorization/quota, and verify API/web smoke tests plus upload/read/delete.

## Relevant references

- [SRS traceability matrix](srs-traceability.md)
- [Evaluation protocol](evaluation-protocol.md)
- [Vercel deployment and acceptance checklist](deployment-vercel.md)
- [API README](../services/api/README.md)
