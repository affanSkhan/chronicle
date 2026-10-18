"""Deterministic evaluation metrics for labelled Chronicle outputs.

This module calculates metrics only. It does not create benchmark labels or
claim performance. Use a curated, held-out dataset and record its provenance.
"""
from collections import Counter
from typing import Any


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def classification_metrics(
    expected: list[str],
    predicted: list[str],
    labels: list[str] | None = None,
) -> dict[str, Any]:
    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted classification arrays must have equal length.")
    if not expected:
        raise ValueError("At least one labelled classification record is required.")
    if any(not isinstance(label, str) or not label for label in expected + predicted):
        raise ValueError("Classification labels must be non-empty strings.")

    evaluated_labels = list(dict.fromkeys(labels or sorted(set(expected) | set(predicted))))
    if not evaluated_labels:
        raise ValueError("At least one label is required.")
    unexpected = (set(expected) | set(predicted)) - set(evaluated_labels)
    if unexpected:
        evaluated_labels.extend(sorted(unexpected))

    per_class = {}
    f1_values = []
    total_tp = total_fp = total_fn = 0
    for label in evaluated_labels:
        tp = sum(e == label and p == label for e, p in zip(expected, predicted))
        fp = sum(e != label and p == label for e, p in zip(expected, predicted))
        fn = sum(e == label and p != label for e, p in zip(expected, predicted))
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        f1 = _ratio(2 * precision * recall, precision + recall)
        support = sum(e == label for e in expected)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
        }
        f1_values.append(f1)
        total_tp += tp
        total_fp += fp
        total_fn += fn

    micro_precision = _ratio(total_tp, total_tp + total_fp)
    micro_recall = _ratio(total_tp, total_tp + total_fn)
    micro_f1 = _ratio(2 * micro_precision * micro_recall, micro_precision + micro_recall)
    return {
        "sample_count": len(expected),
        "accuracy": _ratio(sum(e == p for e, p in zip(expected, predicted)), len(expected)),
        "macro_precision": sum(item["precision"] for item in per_class.values()) / len(per_class),
        "macro_recall": sum(item["recall"] for item in per_class.values()) / len(per_class),
        "macro_f1": sum(f1_values) / len(f1_values),
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": micro_f1,
        "labels": evaluated_labels,
        "per_class": per_class,
    }


def set_retrieval_metrics(expected_ids: list[str], predicted_ids: list[str]) -> dict[str, Any]:
    expected = set(expected_ids)
    predicted = set(predicted_ids)
    true_positive = len(expected & predicted)
    false_positive = len(predicted - expected)
    false_negative = len(expected - predicted)
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return {
        "expected_count": len(expected),
        "predicted_count": len(predicted),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * precision * recall, precision + recall),
    }


def evaluate_records(records: list[dict[str, Any]], dataset_name: str = "unspecified") -> dict[str, Any]:
    if not records:
        raise ValueError("The labelled dataset contains no records.")

    relation_expected: list[str] = []
    relation_predicted: list[str] = []
    expected_impact: list[str] = []
    predicted_impact: list[str] = []
    expected_dependencies: list[str] = []
    predicted_dependencies: list[str] = []

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"Record {index} must be a JSON object.")
        has_expected_relation = record.get("expected_relation") is not None
        has_predicted_relation = record.get("predicted_relation") is not None
        if has_expected_relation != has_predicted_relation:
            raise ValueError(f"Record {index} must provide both expected_relation and predicted_relation.")
        if has_expected_relation:
            relation_expected.append(record["expected_relation"])
            relation_predicted.append(record["predicted_relation"])

        for key, accumulator in (
            ("expected_impacted_ids", expected_impact),
            ("predicted_impacted_ids", predicted_impact),
            ("expected_dependency_edges", expected_dependencies),
            ("predicted_dependency_edges", predicted_dependencies),
        ):
            value = record.get(key, [])
            if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
                raise ValueError(f"Record {index}: {key} must be an array of non-empty strings.")
            accumulator.extend(value)

    output: dict[str, Any] = {
        "dataset_name": dataset_name,
        "record_count": len(records),
        "relation_classification": None,
        "temporal_impact": None,
        "dependency_retrieval": None,
        "limitations": [
            "Metrics are meaningful only when labels are curated independently and the evaluation set is held out from prompt/model tuning.",
            "Aggregation treats identifiers as globally unique; reuse of IDs across examples would distort set-based impact metrics.",
            "This script reports no results unless supplied labelled records contain the relevant expected/predicted fields.",
        ],
    }
    if relation_expected:
        output["relation_classification"] = classification_metrics(relation_expected, relation_predicted)
    if expected_impact or predicted_impact:
        output["temporal_impact"] = set_retrieval_metrics(expected_impact, predicted_impact)
    if expected_dependencies or predicted_dependencies:
        output["dependency_retrieval"] = set_retrieval_metrics(expected_dependencies, predicted_dependencies)
    return output
