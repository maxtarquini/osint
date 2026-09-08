"""Run the synthetic retrieval benchmark without loading application credentials."""

import argparse
import json
from pathlib import Path

from raven.evaluation.retrieval import markdown_report, run_benchmark


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture", type=Path, default=root / "fixtures/evaluation/rx41-retrieval.json"
    )
    parser.add_argument(
        "--output", type=Path, default=root / "docs/research/retrieval-benchmark.json"
    )
    parser.add_argument("--graphiti-result", type=Path)
    args = parser.parse_args()
    report = run_benchmark(args.fixture, graphiti_result=args.graphiti_result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.output.with_suffix(".md").write_text(markdown_report(report), encoding="utf-8")
    print(
        json.dumps(
            {name: method["aggregate"] for name, method in report["methods"].items()}, indent=2
        )
    )


if __name__ == "__main__":
    main()
