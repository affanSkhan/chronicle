"""Shared comparison logic for FF180 A-D baseline evaluation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.evaluation import evaluate_records


ARM_IDS = ("A", "B", "C", "D")
DELTA_METRICS = {
    "relation_classification": ("accuracy", "macro_f1", "micro_f1"),
    "temporal_impact": ("precision", "recall", "f1"),
    "dependency_retrieval": ("precision", "recall", "f1"),
    "ranked_passage_retrieval": (
        "mrr",
        "precision_at_1", "precision_at_3", "precision_at_5", "precision_at_10",
        "recall_at_1", "recall_at_3", "recall_at_5", "recall_at_10",
        "ndcg_at_1", "ndcg_at_3", "ndcg_at_5", "ndcg_at_10",
    ),
}


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: line {line_number} is not valid JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}: line {line_number} must be a JSON object.")
            records.append(record)
    if not records:
        raise ValueError(f"{path}: no JSONL records were found.")
    return records


def _float_metric(result: dict[str, Any], family: str, metric: str) -> float | None:
    value = result.get(family)
    if not isinstance(value, dict):
        return None
    if family == "ranked_passage_retrieval":
        value = value.get("macro_mean")
        if not isinstance(value, dict):
            return None
    output = value.get(metric)
    return float(output) if isinstance(output, (int, float)) else None


def evaluate_ablation_matrix(paths_by_arm: dict[str, Path], dataset_name: str) -> dict[str, Any]:
    if set(paths_by_arm) != set(ARM_IDS):
        raise ValueError("Provide exactly one input file for each configuration A, B, C and D.")

    records_by_arm = {arm: load_jsonl_records(paths_by_arm[arm]) for arm in ARM_IDS}
    ids_by_arm: dict[str, list[str]] = {}
    for arm, records in records_by_arm.items():
        ids = [record.get("record_id") for record in records]
        if any(not isinstance(item, str) or not item.strip() for item in ids):
            raise ValueError(f"Configuration {arm}: every row must have a non-empty record_id.")
        if len(set(ids)) != len(ids):
            raise ValueError(f"Configuration {arm}: record_id values must be unique.")
        ids_by_arm[arm] = ids

    expected_ids = set(ids_by_arm["A"])
    for arm in ARM_IDS[1:]:
        if set(ids_by_arm[arm]) != expected_ids:
            raise ValueError(
                f"Configuration {arm} must contain the exact same record_id set as configuration A."
            )

    metrics_by_arm = {
        arm: evaluate_records(records_by_arm[arm], dataset_name=dataset_name)
        for arm in ARM_IDS
    }
    deltas: dict[str, dict[str, float]] = {}
    for family, metric_names in DELTA_METRICS.items():
        for metric in metric_names:
            baseline = _float_metric(metrics_by_arm["A"], family, metric)
            full = _float_metric(metrics_by_arm["D"], family, metric)
            if baseline is not None and full is not None:
                deltas.setdefault(family, {})[metric] = full - baseline

    return {
        "protocol": "VIIT FF180 A-D comparison",
        "dataset_name": dataset_name,
        "record_count": len(expected_ids),
        "arms": {
            arm: {
                "input_file": str(paths_by_arm[arm]),
                "metrics": metrics_by_arm[arm],
            }
            for arm in ARM_IDS
        },
        "D_minus_A": deltas,
        "interpretation_note": (
            "This report compares supplied labelled predictions only. It does not create labels, "
            "generate predictions, or establish scientific efficacy by itself. Confirm that each arm "
            "used the same model, budgets, prompt policy and held-out records."
        ),
    }
