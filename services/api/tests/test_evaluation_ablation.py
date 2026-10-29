import json
from pathlib import Path

import pytest

from app.services.evaluation_ablation import evaluate_ablation_matrix


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def test_ablation_matrix_requires_same_unique_record_ids(tmp_path):
    arms = {
        "A": _write(tmp_path / "a.jsonl", [{"record_id": "r1", "expected_relation": "supports", "predicted_relation": "supports"}]),
        "B": _write(tmp_path / "b.jsonl", [{"record_id": "r1", "expected_relation": "supports", "predicted_relation": "supports"}]),
        "C": _write(tmp_path / "c.jsonl", [{"record_id": "r2", "expected_relation": "supports", "predicted_relation": "supports"}]),
        "D": _write(tmp_path / "d.jsonl", [{"record_id": "r1", "expected_relation": "supports", "predicted_relation": "supports"}]),
    }
    with pytest.raises(ValueError, match="same record_id set"):
        evaluate_ablation_matrix(arms, "heldout-v1")


def test_ablation_matrix_returns_arm_metrics_and_d_minus_a(tmp_path):
    arms = {}
    for arm in ("A", "B", "C", "D"):
        prediction = "supports" if arm in {"A", "D"} else "contradicts"
        arms[arm] = _write(tmp_path / f"{arm}.jsonl", [{
            "record_id": "r1",
            "expected_relation": "supports",
            "predicted_relation": prediction,
            "expected_impacted_ids": ["claim-1"],
            "predicted_impacted_ids": ["claim-1"] if arm == "D" else [],
        }])
    result = evaluate_ablation_matrix(arms, "labelled-heldout-v1")
    assert result["record_count"] == 1
    assert set(result["arms"]) == {"A", "B", "C", "D"}
    assert result["arms"]["A"]["metrics"]["relation_classification"]["accuracy"] == 1
    assert result["arms"]["D"]["metrics"]["temporal_impact"]["recall"] == 1
    assert result["D_minus_A"]["relation_classification"]["accuracy"] == 0
