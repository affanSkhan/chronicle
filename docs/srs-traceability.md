# Chronicle SRS acceptance traceability

**Basis:** VIIT Software Requirements Specification and revised literature review for “Multi-Agent Research Assistant with Explainable Reasoning.” This matrix records repository evidence and gaps; it is not a declaration that every SRS requirement is complete.

Status definitions:
- **Implemented:** a working code path exists and relevant automated tests cover the behaviour.
- **Partial:** some behaviour exists, but the full acceptance criterion is not yet met.
- **Not implemented:** no working path is verified in the current branch.
- **Not measured:** a harness/protocol may exist, but an independent labelled evaluation or performance run has not been completed.

## Functional requirements

| SRS ID | Requirement area | Evidence in current branch | Status | Remaining work |
|---|---|---|---|---|
| FR-001 | Create, open, rename and archive workspaces | Project routes/UI, soft archive and restore, audit history; test_projects.py | Implemented | Run browser acceptance flow in a deployed environment |
| FR-002 | Specify research question and execution parameters | ResearchRunCreate carries question, mode, source budget and optional project | Partial | Broader domain/date/document filters are not all exposed |
| FR-003 | Four execution modes | Distinct query templates and stage policies in research_planner.py; test_research_planner.py | Implemented | Deterministic planner is not a learned autonomous multi-agent planner |
| FR-004 | Persist bounded execution plan and stages | Plan/query trail saved before provider calls and in run/report snapshots; failed-run persistence test | Implemented | Cost/token budget and durable subtask progress remain incomplete |
| FR-005 | Persist run metadata and source references | SQL run/source/report IDs, configuration and timestamps | Implemented | Full execution fingerprint and per-subtask metadata remain partial |
| FR-006 | Run state includes partial completion | Queued/running/completed/completed_with_limitations/failed/cancel_requested/cancelled; UI surfaces active/cancelled/limited states | Implemented | All statuses are persistent; task progress is not durable across server restarts |
| FR-007 | Cancel and retry failed runs | Owner-scoped cancel/retry endpoints, cooperative cancellation during search/model calls, retry lineage/audit, lifecycle tests | Partial | Cancellation/retry are in-process; durable queue, restart-safe resume, persisted subtasks and distributed cancellation are outstanding |
| FR-008 | Planned scholarly queries | Bounded mode-specific subqueries executed against Crossref/OpenAlex/Semantic Scholar and public-web snippet adapters; provider and query ranks fused with RRF; query trail retained | Implemented | Live provider availability/rate-limit testing still needed |
| FR-009 | Persist source metadata/provenance | DOI/title/authors/year/provider/landing URL/abstract passages persisted | Partial | Raw provider payload and timestamp coverage vary by provider |
| FR-010 | Deduplicate sources | DOI/title dedupe in research pipeline and library import | Partial | Author/year fallback and cross-provider duplicate fixtures need more coverage |
| FR-011 | Validate PDF file/type/size/page count | PDF content-type and signature checks, configurable server byte/page caps, bounded OCR; Vercel upload cap must account for the 4.5 MB function payload limit | Partial | Direct-to-object upload for larger files is not implemented; real-world scan quality still needs sampled testing |
| FR-012 | Page-aware text extraction | Stored passages include page number and text offsets | Implemented | Section segmentation varies by PDF layout |
| FR-013 | OCR scanned documents | Bounded Tesseract fallback for low-text pages; passage methods, OCR page counts, low-text pages, coverage ratio and warnings; test_pdf_ingestion.py | Partial | OCR accuracy is not measured; unsupported languages/poor scans need quality review; Docker image installs English Tesseract |
| FR-014 | Preserve uploaded-file provenance | SHA-256 checksum, storage-backend metadata, page-aware passages, selected-PDF run attachment, and owner-scoped permanent-delete/redaction endpoint | Partial | Durable originals require configured private S3-compatible storage; backup/retention erasure is not implemented |
| FR-015 | Source-linked evidence items | Passage entities and passage/claim relations in graph/passport | Implemented | EvidenceItem is represented via passage plus relation, not as a separate entity |
| FR-016 | Atomic claim candidates | Extraction prompt requests atomic claims and source IDs | Partial | Compound-claim splitting lacks labelled acceptance fixtures |
| FR-017 | Claims must be supported or marked uncertain | Generated claims remain unreviewed and link to exact source passage IDs | Partial | Executive summaries are not decomposed into individually traced claim records |
| FR-018/019 | Citation support and contradiction labels | Model-assisted verifier returns structured verdict, checks passage IDs, stores audit and review-required state | Partial | No labelled verifier benchmark has been run |
| FR-020 | Resolve DOI/URL validity | DOI/provider status checks exist | Partial | General DOI resolution outcome is not consistently surfaced per source |
| FR-021 | Evidence rationale and uncertainty | Verifier returns concise rationale, exact passage references and uncertainty notes | Implemented | Output quality still requires independent human adjudication/evaluation |
| FR-022 | Graph from source to recommendation | Graph contains paper/version/passage/study/claim nodes | Partial | Conclusion/recommendation nodes are not first-class graph entities |
| FR-023 | Typed provenance relations | Supports/contradicts/qualifies/not-comparable/depends-on and paper dependency edges | Partial | Not every SRS relation type is represented in all route schemas |
| FR-024 | Inferred relation provenance | Model-inferred/metadata-inferred basis and rationale/signal are retained | Implemented | Scores are heuristics and are not calibrated probabilities |
| FR-025 | Detect likely source dependence | Run-scoped suggestions use known dataset/registry identifiers and near-duplicate abstracts; researcher confirms links | Partial | Citation ancestry and generic derivatives are not detected; precision/recall not measured |
| FR-026 | Distinguish raw sources from dependent clusters | Pair-level dependency suggestions carry supporting signals | Partial | Full cluster grouping and per-claim independent-source counts are missing |
| FR-027 | Navigate claim → passage → source | Selectable evidence graph and Evidence Passport trace IDs | Partial | End-to-end report finding click-through and browser test needed |
| FR-028 | Context-aware conflict comparison | Study context fields, synthesis disagreement schema and comparability prompt | Partial | Population/method/outcome comparability requires labelled evaluation |
| FR-029 | Classification performance by relation type | Metric functions exist in evaluation.py | Not measured | Need a frozen, adjudicated test set and recorded output |
| FR-030 | Show failed subqueries and coverage limitations | Provider errors and scope limits appear in report snapshots | Implemented | Add a dedicated UI panel for each failed subtask |
| FR-031 | Make uncertainty explicit | Abstract-only limitation, review state, uncertainty notes and uncalibrated-score notice | Partial | A unified uncertainty ledger remains to build |
| FR-032 | Counter-evidence pass | Forensic query variants explicitly search conflict/contradiction language | Partial | No iterative adversarial search agent or ablation study |
| FR-033 | Track event and observed times | Source event/status-check/audit records timestamp events | Implemented | Event time depends on what provider metadata supplies |
| FR-034 | Manual and scheduled source refresh | Manual check and opt-in polling workflow exist | Partial | Scheduler is process-local; multi-replica coordination is not guaranteed |
| FR-035 | Propagate changes through dependencies | Directed multi-hop dependencies and symmetric shared-dataset/overlap impact review; regression covers a three-paper chain and dependent claims | Partial | Impact precision/recall and real-event coverage remain not measured |
| FR-036 | Reverify or mark pending review | Source events flag claims/report versions; citation verifier is available to reviewers | Partial | Automated queued reverification after a source event is not implemented |
| FR-037 | Preserve report versions | Source update creates a new report version and retains prior version | Implemented | Browser workflow smoke test still required |
| FR-038 | Explain before/after change impact | Impact summary records affected papers/claims/report versions and review reasons | Partial | Full claim-by-claim before/after assessment diff is incomplete |
| FR-039 | Do not auto-declare downstream claims false | Updates flag claims/report versions for review; regression asserts no automatic contradicted verdict | Implemented | Extend regression coverage to cycles, mixed relationship types and real event notices |
| FR-040 | Notify users of important events | No notification queue | Not implemented | Optional requirement |
| FR-041 | Structured research report | Academic Discovery Snapshot covers sources, findings, limitations, uncertainties and candidate opportunities | Partial | PDF report export and stricter section-completeness validation |
| FR-042 | Distinguish fact from model inference | Provenance labels, abstract-only notice, human-review warning | Partial | Every summary statement is not separately linked to a claim record |
| FR-043 | Filterable Evidence Ledger | Graph supports search and node-type filtering; source timeline is separate | Partial | Need filters for claim status, edge type, source event and unresolved issue |
| FR-044 | Human-readable and machine-readable export | Markdown, JSON and PDF Evidence Passport exports; PDF generation uses existing PyMuPDF dependency | Partial | Verify layout across representative long passports and complete browser download acceptance |
| FR-045 | Export source limitations | Passport/report include coverage and interpretation limitations | Implemented | Provider-failure export fixtures should be expanded |
| FR-046/047 | Research opportunity with prior-art/falsification plan | Synthesis schema/UI carries evidence IDs, prior-art queries, alternatives and falsification plan | Partial | Not an automated graph-based research-gap detector |
| FR-048 | Do not claim novelty from sparse results | Opportunities explicitly say candidate only and require prior-art review | Implemented | Test with deliberately incomplete source coverage |
| FR-049 | Hypothesis module configurable | Hypothesis Lab consumes optional synthesis | Partial | Explicit feature configuration switch is missing |
| FR-050 | Human review/annotation | Relation review actions and audit history | Partial | Direct claim-level annotations are less complete than relation review |
| FR-051 | Audit consequential changes | Audit events cover run/project, claims/edges, dependency links, source events and report versions | Implemented | Broader audit-export tests desirable |
| FR-052 | Actionable errors | API structured errors and UI error state | Partial | Full failure-mode UX smoke suite is absent |
| FR-053 | Safe diagnostic metadata | Errors are usually surfaced without raw provider payload | Partial | Secret-sentinel and log-redaction tests absent |
| FR-054 | Delete workspace/data | Soft archive preserves records | Partial | Permanent delete/retention workflows are not implemented |

## Non-functional requirements and acceptance tests

| Area | Evidence | Status | Required follow-up |
|---|---|---|---|
| Tenant isolation / security | Authenticated routes, ownership filters, auth tests and project ownership tests | Implemented for tested endpoints | Audit every private route and run a dedicated security review |
| Privacy/data-flow disclosure | Research UI warns that queries go to metadata providers and passages may go to configured model provider | Implemented | Validate disclosure language/policies for production deployment |
| Prompt-injection resistance | Claim extraction/synthesis/verifier prompts treat source text as untrusted; adversarial fixture tests | Partial | Run a larger red-team corpus; prompt instructions alone do not guarantee safety |
| Bounded workload | Source budget capped at 50 and planned query budgets | Partial | Durable queue, cancellation, model token/cost budgets and rate limiting |
| AT-01..AT-03 core workflow/PDF/citation | API integration/unit tests for research runs, PDF passages and citation checks | Partial | Complete acceptance run through a real deployment with external provider |
| AT-04 dependency precision/recall | Evaluation harness accepts expected/predicted dependency edges | Not measured | Curated labelled dependency set and recorded held-out results |
| AT-05 relation classification | Per-class precision/recall/F1 helpers | Not measured | Freeze labelled context/contradiction test set before evaluation |
| AT-06 temporal impact | Set-based temporal impact metrics, direct source-event tests, and new multi-hop regression | Not measured | Create an adjudicated labelled set; report precision, recall, F1, false alarms and missed high-impact entities |
| AT-07 report history | Report version and source-event tests | Implemented | Browser acceptance test still needed |
| AT-08 prompt injection | Prompt-injection and source-pointer filtering tests | Partial | Adversarial evaluation beyond a few unit tests |
| AT-09 account isolation | Test coverage for authentication and project ownership | Implemented for tested routes | Route-by-route tenant audit |
| AT-10 export integrity | Markdown/JSON export tests plus PDF response/header, searchable-text and invalid-format regression tests | Partial | Browser download acceptance and larger multi-page passport fixture remain |
| AT-11 provider failures | Partial-query error path and failed-run plan persistence tests | Partial | Real provider outage and UI verification |
| AT-12 performance | No reproducible load/latency results | Not measured | Benchmark with recorded hardware, dataset, request profile and P50/P95 |
| Literature-review contribution | Versioned dependencies and temporal propagation into claims/report versions | Partial | Evaluate dependency detection and temporal impact against an adjudicated holdout set |


## Current hardening-branch additions

The merged `feat/ff180-final-hardening` work provides Semantic Scholar/public-web discovery, bounded LangGraph planner/critic execution, durable PDF bytes through `uploaded_pdf_blobs` (migration 0008), an opt-in PostgreSQL queue/worker, and ranked retrieval metrics. The active `feat/ff180-objective-completion` branch adds explicit runtime A–D arm controls, recorded evidence-gap iterations, persisted report-version conclusions, claim/passage provenance edges, owner-scoped conclusion list/review endpoints, human review controls in the graph UI, Evidence Passport conclusion exports, temporal conclusion re-versioning, and deletion cleanup. API CI, web CI and container CI passed on reviewed prior commits; verify the final head before merge. This branch adds migration 0009 for conclusion storage, which must be explicitly applied before deploying the schema-dependent code. Dense embeddings require `HF_TOKEN`; private S3-compatible storage is optional after migration 0008 but preferred for larger uploads.

## Research-integrity policy

The defensible contribution is the integrated workflow for **versioned source dependence and temporal change-impact propagation into saved claims and report versions**. Chronicle does not claim RAG, citation checking, knowledge graphs, or multi-agent orchestration alone as novel.

No benchmark accuracy, contradiction F1, dependency precision/recall, temporal impact precision/recall, latency or throughput is claimed unless a labelled held-out evaluation or reproducible benchmark run is recorded. Unit-test fixtures validate code paths, not scientific accuracy.


## Temporal source-event reassessment

The current code exposes a researcher-triggered, owner-scoped, bounded reassessment endpoint for claims affected by a recorded source event. Results are retained in audit history and claims remain flagged for human review. This does not automatically establish scientific falsity. Persistent conclusions are cloned to the new report version after a source event and returned to `needs_review`; old report/conclusion versions remain preserved. Durable queued reassessment, automatic promotion of provider signals into authoritative events, and empirical temporal-impact precision/recall remain incomplete.
