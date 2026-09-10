"""Run the evaluation from the command line.

    python -m overturn.eval --extractor oracle
    python -m overturn.eval --extractor null
    python -m overturn.eval --extractor model            # uses config/models.yaml
    OVERTURN_MODEL_PROVIDER=anthropic python -m overturn.eval --extractor model
    OVERTURN_AGENTCORE_ARN=arn:... python -m overturn.eval --extractor agentcore

The calibration extractors (oracle, null) check the harness; their results are never
presented as the product's numbers. ``model`` runs the real extraction agent in this
process and ``agentcore`` runs it on Amazon Bedrock AgentCore; both write through the real
ledger tools, one fresh agent per document, and both call a paid model for every letter.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from overturn.engine.packs import PackRegistry
from overturn.eval.corpus import build_corpus
from overturn.eval.harness import OracleExtractor, null_extractor, run_eval

ROOT = Path(__file__).resolve().parents[2]


def _model_backed(mode: str):
    from overturn.agents.factory import extractor_from_env
    from overturn.models.factory import describe

    if mode == "model":
        print(f"# {describe('extraction')}", file=sys.stderr)
    else:
        print(
            f"# AgentCore runtime {os.environ.get('OVERTURN_AGENTCORE_ARN', '?')}", file=sys.stderr
        )
    return extractor_from_env({**os.environ, "OVERTURN_EXTRACTOR": mode})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m overturn.eval")
    parser.add_argument(
        "--extractor", choices=("oracle", "null", "model", "agentcore"), default="oracle"
    )
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--packs", type=Path, default=ROOT / "packs")
    parser.add_argument("--limit", type=int, default=None, help="score only the first N letters")
    parser.add_argument(
        "--failures", action="store_true", help="list every non-correct field outcome"
    )
    args = parser.parse_args(argv)

    corpus = build_corpus(args.seed)
    if args.limit:
        corpus = corpus[: args.limit]
    registry = PackRegistry.from_directory(args.packs)

    if args.extractor == "oracle":
        extractor = OracleExtractor(corpus)
    elif args.extractor == "null":
        extractor = null_extractor
    else:
        extractor = _model_backed(args.extractor)

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
