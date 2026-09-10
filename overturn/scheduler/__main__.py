"""Run the background tick.

    python -m overturn.scheduler --once
    python -m overturn.scheduler --interval 900
    OVERTURN_EXTRACTOR=model python -m overturn.scheduler

Uses the same environment as the API: OVERTURN_DATA_DIR, OVERTURN_EXTRACTOR and
OVERTURN_TODAY.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from overturn.engine.packs import PackRegistry
from overturn.ledger.store import CaseStore
from overturn.pipeline import Pipeline
from overturn.scheduler import DEFAULT_INTERVAL_SECONDS, Scheduler, TickReport

ROOT = Path(__file__).resolve().parents[2]


def _print(report: TickReport) -> None:
    print(report.summary(), flush=True)
    for case_id, question in report.new_questions:
        print(f"  new  {case_id}  {question}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m overturn.scheduler")
    parser.add_argument(
        "--data", type=Path, default=Path(os.environ.get("OVERTURN_DATA_DIR", ROOT / "data"))
    )
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--once", action="store_true", help="tick once and exit")
    args = parser.parse_args(argv)

    from overturn.agents.factory import extractor_from_env
    from overturn.telemetry import setup_from_env

    setup_from_env()
    extractor = extractor_from_env()
    pipeline = Pipeline(
        CaseStore(args.data), PackRegistry.from_directory(ROOT / "packs"), extractor
    )
    from overturn.retention import retention_days_from_env

    scheduler = Scheduler(pipeline, retention_days=retention_days_from_env())
    fixed = os.environ.get("OVERTURN_TODAY")

    if args.once:
        _print(scheduler.tick(today=date.fromisoformat(fixed) if fixed else None))
        return 0

    print(f"Ticking every {args.interval:.0f}s over {args.data}. Ctrl+C to stop.", flush=True)
    try:
        scheduler.run(args.interval, on_tick=_print)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
