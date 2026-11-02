# Synthetic evaluation smoke artifact

`synthetic-smoke-v1.jsonl` is a two-record, hand-authored smoke fixture for
checking that Chronicle's evaluation harness emits relation, retrieval,
dependency, citation, grounding, and temporal-impact metrics. It is not a
scientific benchmark, is not held out, and must not be used to claim model
efficacy. Replace it with a licensed, adjudicated dataset before reporting
research results.

The committed output was generated with:

```powershell
python services/api/scripts/evaluate_labeled_jsonl.py evaluation/pilot/synthetic-smoke-v1.jsonl `
  --dataset-name synthetic-smoke-v1 `
  --output evaluation/pilot/synthetic-smoke-v1.metrics.json
```
