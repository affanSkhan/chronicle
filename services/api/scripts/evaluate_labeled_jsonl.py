"""Evaluate Chronicle predictions against a labelled JSONL file.

Example:
    python scripts/evaluate_labeled_jsonl.py ../evaluation/labelled-example.jsonl --dataset-name pilot --output metrics.json

Each line is a JSON object. For relation classification, use
expected_relation/predicted_relation. For temporal impact, use
expected_impacted_ids/predicted_impacted_ids. For source dependency retrieval,
use expected_dependency_edges/predicted_dependency_edges.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.evaluation import evaluate_records


def load_records(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Line {line_number} is not valid JSON: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Line {line_number} must be a JSON object.")
            records.append(payload)
    if not records:
        raise ValueError("The input file contains no JSONL records.")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate labelled Chronicle predictions.")
    parser.add_argument("input", type=Path, help="Path to a curated labelled JSONL file.")
    parser.add_argument("--dataset-name", default="unspecified", help="Dataset identifier and version.")
    parser.add_argument("--output", type=Path, help="Optional path to save metrics JSON.")
    args = parser.parse_args()

    try:
        metrics = evaluate_records(load_records(args.input), dataset_name=args.dataset_name)
    except (OSError, ValueError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(metrics, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
