"""How long a finished file is kept.

Case files hold health information. Overturn keeps them only as long as they are useful
(OVERTURN.md §9.3): a file is removed once it is finished — overturned, upheld and not
taken further, or closed — and has not changed for the retention period. An open file is
never purged, however old it is. Removal takes everything: the case, its document text
and its write audit.

    python -m overturn.retention --days 30 --dry-run
    OVERTURN_RETENTION_DAYS=30 python -m overturn.scheduler     # applied on every tick
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from overturn.ledger.schema import CaseState, utcnow
from overturn.ledger.store import CaseStore

DEFAULT_RETENTION_DAYS = 30
"""Short by default. An organisation that must keep records longer sets it explicitly."""

FINISHED_STATES = frozenset(
    {
        CaseState.RESOLVED_OVERTURNED,
        CaseState.RESOLVED_UPHELD,
        CaseState.CLOSED_DEADLINE_MISSED,
    }
)


@dataclass
class PurgeReport:
    examined: int = 0
    purged: list[str] = field(default_factory=list)
    kept_open: int = 0
    kept_recent: int = 0

    def summary(self) -> str:
        return (
            f"{self.examined} files examined: {len(self.purged)} finished files removed, "
            f"{self.kept_recent} finished but recent, {self.kept_open} still open"
        )


def retention_days_from_env(env: dict[str, str] | None = None) -> int | None:
    """The configured period, or None when retention is not configured."""
    raw = (env if env is not None else os.environ).get("OVERTURN_RETENTION_DAYS", "").strip()
    if not raw:
        return None
    days = int(raw)
    if days < 1:
        raise ValueError("OVERTURN_RETENTION_DAYS must be at least 1")
    return days


def purge_finished(
    store: CaseStore,
    *,
    older_than_days: int,
    now: datetime | None = None,
    dry_run: bool = False,
) -> PurgeReport:
    """Remove finished files untouched for longer than the retention period."""
    cutoff = (now or utcnow()) - timedelta(days=older_than_days)
    report = PurgeReport()
    for case_id in store.list_case_ids():
        report.examined += 1
        case = store.load(case_id)
        if case.state not in FINISHED_STATES:
            report.kept_open += 1
            continue
        if case.updated_at > cutoff:
            report.kept_recent += 1
            continue
        if not dry_run:
            _remove(store, case_id)
        report.purged.append(case_id)
    return report


def _remove(store: CaseStore, case_id: str) -> None:
    store.path_for(case_id).unlink(missing_ok=True)
    store.audit_path(case_id).unlink(missing_ok=True)
    texts = Path(store.root) / "texts" / case_id
    if texts.exists():
        shutil.rmtree(texts)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(prog="python -m overturn.retention")
    parser.add_argument(
        "--data", type=Path, default=Path(os.environ.get("OVERTURN_DATA_DIR", root / "data"))
    )
    parser.add_argument(
        "--days", type=int, default=retention_days_from_env() or DEFAULT_RETENTION_DAYS
    )
    parser.add_argument("--dry-run", action="store_true", help="report without removing")
    args = parser.parse_args(argv)

    report = purge_finished(CaseStore(args.data), older_than_days=args.days, dry_run=args.dry_run)
    print(("Would remove: " if args.dry_run else "") + report.summary())
    for case_id in report.purged:
        print(f"  {case_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
