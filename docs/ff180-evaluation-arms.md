# FF180 A–D runtime evaluation arms

Chronicle now accepts an optional `evaluation_arm` field on research-run creation. The setting is persisted in the run configuration and returned in the run response, and the report's execution plan records the applied feature flags.

## Request

Send four runs using the same research question, PDF set, `max_sources`, provider/model configuration, and evaluation dataset/split. Example:

```http
POST /api/v1/research/runs
Authorization: Bearer <access-token>
Content-Type: application/json
```

```json
{
  "question": "How does evidence provenance improve research reliability?",
  "mode": "academic",
  "max_sources": 10,
  "source_paper_ids": [],
  "evaluation_arm": "B",
  "execute": true
}
```

Use `A`, `B`, `C`, and `D` for separate runs. Omit `evaluation_arm` for normal full-lifecycle behaviour (arm D). All output claims remain model-inferred until human review.

## Arms

| Arm | Enabled behaviour | Deliberately omitted |
|---|---|---|
| A — Standard RAG | One original-question search pass and optional synthesis | Agent-led query planning, follow-up iterations, claim graph, dependency scan, temporal impact propagation |
| B — Iterative research agent | Bounded planned queries, up to two evidence-gap follow-up searches, optional synthesis | Persisted claim/provenance graph and temporal impact propagation |
| C — Claim and provenance graph | Planned/follow-up retrieval, claim extraction, evidence relations, dependency candidate scan and review records | Temporal source-event impact propagation |
| D — Full lifecycle | C features plus temporal impact propagation and targeted review/re-verification endpoints | Nothing from this ablation matrix |

The follow-up search is deliberately bounded and deterministic: at most two additional focused queries are tried, and no more than five total queries or the source budget are allowed. It is a controlled experiment arm, not a claim that Chronicle implements an open-ended autonomous research agent.

## Evaluation protocol

1. Freeze the same labelled examples and record IDs for all arms.
2. Keep provider/model ID, prompt version, token/search/source budgets, uploaded documents and dataset split constant.
3. Record the run IDs, commit SHA, model/provider settings, timestamps and output JSONL for each arm.
4. Run `services/api/scripts/evaluate_ablation_matrix.py` with one prediction file per arm. The evaluator rejects duplicate or mismatched record-ID sets.
5. Publish only measured held-out metrics. Synthetic tests validate software behaviour; they are not scientific benchmark results.

The runtime arm selection now exists, but benchmark values still must come from real predictions on a licensed dataset and a human-adjudicated temporal-update set. No score is inferred from a deployment or unit test.
