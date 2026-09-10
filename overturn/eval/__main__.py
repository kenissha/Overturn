"""Run the evaluation from the command line.

    python -m overturn.eval --extractor oracle
    python -m overturn.eval --extractor null --markdown

The model-backed extractor is added once the agent layer exists; until then only the
calibration extractors are available, and their results are never presented as the
product's numbers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from overturn.engine.packs import PackRegistry
from overturn.eval.corpus import build_corpus
from overturn.eval.harness import OracleExtractor, null_extractor, run_eval

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m overturn.eval")
    parser.add_argument("--extractor", choices=("oracle", "null"), default="oracle")
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--packs", type=Path, default=ROOT / "packs")
    parser.add_argument(
        "--failures", action="store_true", help="list every non-correct field outcome"
    )
    args = parser.parse_args(argv)

    corpus = build_corpus(args.seed)
    registry = PackRegistry.from_directory(args.packs)
    extractor = OracleExtractor(corpus) if args.extractor == "oracle" else null_extractor

    report = run_eval(corpus, extractor, registry, name=args.extractor)
    print(report.to_markdown())

    if args.failures:
        print()
        for result in report.results:
            for name, outcome in result.outcomes.items():
                if outcome.value not in ("correct", "correct_abstention"):
                    print(f"{result.sample_id}  {name:32}  {outcome.value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
