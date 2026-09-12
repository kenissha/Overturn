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


_CREDENTIAL_HINTS: tuple[tuple[str, str], ...] = (
    (
        "NoCredentialsError",
        "No AWS credentials were found. Set them in ~/.aws/credentials, or export "
        "AWS_BEARER_TOKEN_BEDROCK with a Bedrock API key.",
    ),
    (
        "UnrecognizedClientException",
        "AWS rejected the credentials. Check the access key or Bedrock API key, and that "
        "it belongs to the account you granted model access in.",
    ),
    (
        "AccessDeniedException",
        "AWS accepted the credentials but refused the call. A new account is verified "
        "before it may invoke models, and Anthropic models need the use-case form "
        "submitted once in the Bedrock console.",
    ),
    (
        "ResourceNotFoundException",
        "That model id does not exist in this region. Copy the id the Bedrock console "
        "shows and set OVERTURN_MODEL_ID_EXTRACTION, or change the region.",
    ),
    (
        "ValidationException",
        "Bedrock rejected the request shape. If the console shows an inference-profile id "
        "(one starting with a region, such as us.anthropic.*), set "
        "OVERTURN_MODEL_ID_EXTRACTION to it.",
    ),
    (
        "ThrottlingException",
        "Bedrock is throttling this account. Wait, or run fewer letters with --limit.",
    ),
)


def _credentials_hint(exc: BaseException) -> str | None:
    """A short, actionable line for the failures a first run actually hits."""
    text = f"{type(exc).__name__}: {exc}"
    for marker, hint in _CREDENTIAL_HINTS:
        if marker in text:
            first = text.splitlines()[0][:300]
            return f"Nothing was scored. {hint}{chr(10)}{chr(10)}  {first}"
    return None


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

    try:
        report = run_eval(corpus, extractor, registry, name=args.extractor)
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is a known setup failure
        hint = _credentials_hint(exc)
        if hint is None:
            raise
        print(hint, file=sys.stderr)
        return 2
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
