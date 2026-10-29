# Chronicle Evaluation Protocol

## Purpose

This protocol describes how to evaluate Chronicle's claim-relation classification, source-dependency retrieval, and temporal impact propagation. **No benchmark result should be reported until the dataset has been labelled, the split has been frozen, and the evaluator has been run against predictions from that frozen split.**

## Dataset design

Use a dataset with explicit provenance and a versioned label guide. Candidate public resources to review for licensing and task fit include SciFact / SciFact-Open for scientific claim verification, and LitQA2 or ScholarQABench for research-question answering. These benchmarks do not directly provide all Chronicle-specific temporal labels, so do not treat their labels as temporal-impact ground truth without a carefully documented mapping.

Create a separate human-labelled temporal-update set containing:
- an initial source paper and verifiable update/retraction/correction notice;
- the dependency relationships between the updated source and downstream papers;
- claims and saved report versions affected by that source;
- expected impacted entity identifiers;
- annotator rationale and adjudication status.

For temporal labels, use at least two annotators on a pilot set, resolve disagreements with an explicit adjudication pass, and freeze the test labels before model/prompt tuning. Preserve dataset license, version, sampling method, annotation instructions, annotator roles (not personal details), and split membership.

## JSONL input schema

Each line is a JSON object. You may evaluate one or several metric families in the same file.

```json
{
  "record_id": "stable-example-id",
  "expected_relation": "supports",
  "predicted_relation": "supports",
  "expected_impacted_ids": ["claim-id-1", "report-version-id-2"],
  "predicted_impacted_ids": ["claim-id-1"],
  "expected_dependency_edges": ["paper-a->paper-b"],
  "predicted_dependency_edges": ["paper-a->paper-b"]
}
```

The identifiers and labels above are illustrative schema values, not benchmark examples or performance data. Permitted relation labels must be documented and normalized consistently before evaluation. Records may omit metric families they do not evaluate, but should not mix incompatible label taxonomies in one split.

## Metric definitions

### Relation classification
- **Accuracy:** correctly predicted labels / all labelled items.
- **Per-class precision:** TP / (TP + FP).
- **Per-class recall:** TP / (TP + FN).
- **Per-class F1:** harmonic mean of precision and recall.
- Report macro-F1 to make class-specific weaknesses visible, and micro-F1 for an aggregate view. Include per-class support and confusion counts; do not report accuracy alone for imbalanced labels.

### Temporal impact
Treat each record's expected impacted ID set as the gold set and the predicted impacted ID set as the system set:
- **Precision:** true positive impacted IDs / all predicted impacted IDs.
- **Recall:** true positive impacted IDs / all expected impacted IDs.
- **F1:** harmonic mean of precision and recall.
- Also report false alarms per source event, missed high-severity downstream changes, and time from source-update detection to recorded review flag when timestamps are available.

### Dependency retrieval
Evaluate labelled source-dependency edges as sets, and report precision, recall and F1. If a dependency edge includes direction or a relation type, compare canonical typed edges, not just unordered paper pairs.

The current CLI uses identifiers as sets within each JSONL file. If different records reuse identical identifiers, they can collide in aggregate set-based metrics; use globally unique IDs in the evaluation file or extend the evaluator to group metrics by record before publication.

## Reproducible run

From the repository root, after creating an approved labelled JSONL file under `evaluation/`:

```bash
cd services/api
python scripts/evaluate_labeled_jsonl.py ../../evaluation/your-labelled-split.jsonl \
  --dataset-name your-dataset-version-and-split \
  --output ../../evaluation/results/your-run.json
```

Save the input file hash, repository commit SHA, model/provider ID, prompt revision, parameters, dataset version, split ID, and output metrics with each run. Do not run prompt tuning against the test split; use train/dev for development and run the held-out test once per documented release/evaluation plan.

## Required reporting

A research result should state the dataset and version, sampling strategy, annotation agreement/adjudication approach, split sizes, label distribution, exclusions, missing data, provider failures, model/prompt version, confidence intervals where justified, and limitations. Evaluate important strata separately, including update type (retraction/correction/expression of concern), dependency depth, and source/claim relationship class.

No results are claimed by this repository until a labelled, documented, held-out evaluation has actually been run. Synthetic unit-test inputs validate the metric implementation only; they are not scientific benchmark evidence.


## Approved FF180 A–D comparison

The approved synopsis defines four configurations under the same model and budgets:

- **A — Standard RAG:** single-pass retrieval and answer generation without agent-led research planning.
- **B — Iterative research agent:** bounded query planning/research iterations and synthesis, but no persisted claim/provenance graph or temporal propagation.
- **C — Claim and provenance graph:** source-linked claims and relations without temporal source-event propagation.
- **D — Full lifecycle prototype:** the graph plus source-event impact propagation, targeted reassessment, report versioning and audit.

The machine-readable definitions live in `evaluation/ablation-configurations.json`. `scripts/evaluate_ablation_matrix.py` compares prediction JSONL files for all four arms and requires the same unique `record_id` set in each file. It emits metrics and D-minus-A deltas without creating predictions or ground-truth labels.

**Important:** the current app does not yet expose strict A/B/C/D runtime feature flags for every arm. The recipes in the manifest are operational definitions for a controlled evaluation; the evaluator is ready for saved outputs, but no A–D benchmark result is claimed until the arms are run with matching model ID, source/token budgets, datasets, split and prompts. The two-node query-planning graph is not a full iterative agent by itself.

The metrics harness also reports MRR, Precision@K, Recall@K and NDCG@K for ranked passage retrieval when the input provides `expected_passage_ids` and `predicted_ranked_passage_ids`. These are ranking metrics, not scientific accuracy.


## Extended labelled-record fields

The evaluator accepts optional, independently labelled fields in each JSONL record:

- Claim-to-passage support: `expected_support_passage_ids` and `predicted_support_passage_ids`. These produce per-record and pooled precision/recall/F1.
- Citation review indicators: `citation_count`, `supported_citation_count`, `claim_count`, `claims_with_citations`, and `grounded_claim_count`. All five fields must be present together. The output includes citation-support precision, claim citation coverage, and exact-passage grounding rate. These are transparent labelled indicators, **not** a complete automated ALCE score.
- Temporal impacts per source event: `expected_impacted_ids` and `predicted_impacted_ids` can be supplied on each event record. The evaluator reports per-event macro metrics, pooled counts, false alarms per source event and missed impact counts.
- High-severity impact: `expected_high_severity_impacted_ids` and `predicted_high_severity_impacted_ids` produce recall and the number of missed high-severity entities.
- Detection delay: optional `detection_latency_seconds` is supplied from recorded timestamps and reported as mean/P95 seconds.

The A–D comparison runner requires the same unique `record_id` set in all four arm files. It reports per-arm metrics and D-minus-A deltas where both arms provide the metric. It does not itself produce each arm's predictions, and the application does not yet expose strict runtime flags for all four configurations.
