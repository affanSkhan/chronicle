"""Compare the approved FF180 A-D arms using identical labelled records."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.evaluation_ablation import evaluate_ablation_matrix


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare labelled FF180 A-D prediction files.")
    parser.add_argument("--dataset-name", required=True, help="Dataset/version/split identifier.")
    parser.add_argument("--config", action="append", required=True, metavar="ARM=PATH")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()
    paths: dict[str, Path] = {}
    for raw in args.config:
        if "=" not in raw:
            parser.error("--config must be specified as ARM=PATH.")
        arm, filename = raw.split("=", 1)
        arm = arm.strip().upper()
        if arm not in {"A", "B", "C", "D"} or not filename.strip():
            parser.error("--config must use A, B, C or D and a non-empty path.")
        if arm in paths:
            parser.error(f"Configuration {arm} was supplied more than once.")
        paths[arm] = Path(filename)
    try:
        report = evaluate_ablation_matrix(paths, args.dataset_name)
    except (OSError, ValueError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
