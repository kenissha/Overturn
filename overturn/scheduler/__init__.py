"""The background tick: files move forward without anyone opening them.

On every tick, each open case is processed: unread denial letters are read, and the
deterministic layer re-evaluates the case against today's date. That is all a tick does.
It cannot send, submit or notify anyone, because nothing in the codebase can.

Evaluation is idempotent and escalation identities are stable, so a tick over an unchanged
case changes nothing and raises nothing new. What a tick *can* produce is a new question —
most often because a deadline crossed into a pressure band overnight. New questions land
in the morning queue, which is the only place the system speaks.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from overturn.ledger.schema import CaseState
from overturn.pipeline import Pipeline
from overturn.retention import purge_finished

DEFAULT_INTERVAL_SECONDS = 15 * 60

CLOSED_STATES = frozenset(
    {
        CaseState.RESOLVED_OVERTURNED,
        CaseState.RESOLVED_UPHELD,
        CaseState.CLOSED_DEADLINE_MISSED,
    }
)
"""Finished files. Everything else is ticked, including filed ones: the plan's response
clock keeps running after the appeal goes out."""


@dataclass
class TickReport:
    on: date
    cases: int = 0
    documents_read: int = 0
    open_questions: int = 0
    new_questions: list[tuple[str, str]] = field(default_factory=list)
    """(case_id, question) for every escalation not seen on an earlier tick."""
    purged: int = 0

    def summary(self) -> str:
        return (
            f"{self.on.isoformat()}: {self.cases} open files, {self.documents_read} documents "
            f"read, {self.open_questions} open questions, {len(self.new_questions)} new"
            + (f", {self.purged} finished files removed" if self.purged else "")
        )


class Scheduler:
    def __init__(
        self,
        pipeline: Pipeline,
        state_path: Path | None = None,
        *,
        retention_days: int | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.retention_days = retention_days
        self.state_path = state_path or Path(pipeline.store.root) / "scheduler.json"

    def tick(self, *, today: date | None = None) -> TickReport:
        """Process every open case once. Safe to run as often as you like."""
        today = today or date.today()
        seen = self._seen()
        report = TickReport(on=today)
        current: set[str] = set()

        for case_id in self.pipeline.store.list_case_ids():
            if self.pipeline.store.load(case_id).state in CLOSED_STATES:
                continue
            report.cases += 1
            if self.pipeline.extractor is not None:
                report.documents_read += self.pipeline.extract_pending(case_id)
            for escalation in self.pipeline.evaluate(case_id, today=today).escalations:
                current.add(escalation.escalation_id)
                if escalation.escalation_id not in seen:
                    report.new_questions.append((case_id, escalation.question))

        report.open_questions = len(current)
        if self.retention_days is not None:
            purged = purge_finished(self.pipeline.store, older_than_days=self.retention_days)
            report.purged = len(purged.purged)
        self._remember(seen | current)
        return report

    def run(
        self,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        *,
        stop: threading.Event | None = None,
        on_tick: Callable[[TickReport], None] | None = None,
    ) -> None:
        """Tick until stopped. A failing tick is reported and the loop carries on."""
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                report = self.tick()
                if on_tick is not None:
                    on_tick(report)
            except Exception as exc:  # a bad file must not stop every other file
                print(f"tick failed: {type(exc).__name__}: {exc}")
            stop.wait(interval_seconds)

    # -- which questions have already been surfaced -----------------------------------

    def _seen(self) -> set[str]:
        try:
            return set(json.loads(self.state_path.read_text(encoding="utf-8"))["seen"])
        except (FileNotFoundError, KeyError, ValueError):
            return set()

    def _remember(self, seen: set[str]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.state_path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"seen": sorted(seen)}, fh)
        os.replace(tmp, self.state_path)
