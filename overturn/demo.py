"""Seed a demonstration workspace from the evaluation corpus.

    python -m overturn.demo --reset
    OVERTURN_DATA_DIR=data/demo uvicorn --factory overturn.api.app:app_from_env

This exists so the interface can be seen working without model credentials, and it is
explicit about what it is:

- The letters are the synthetic evaluation corpus, not real correspondence.
- Facts are written from the corpus answer key, through the same agent-facing tool the
  extraction agent uses — quote and page, with the span located and verified by the
  ledger. The audit trail names the writer ``AnswerKey@demo (not a model)``. Nothing
  seeded here is model output and it must not be presented as such.
- Most files are then advanced the way a person would advance them — critical facts
  confirmed, documents marked on file, some recorded as filed — by an actor named
  ``demo-seed``, so the queue shows what forty-odd files look like when most of them are
  progressing quietly and a few need someone today.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from overturn.engine.packs import PackRegistry
from overturn.eval.corpus import Sample, build_corpus
from overturn.extraction import ExtractionInput
from overturn.ledger.documents import normalise
from overturn.ledger.fields import FactKind, get_field
from overturn.ledger.schema import CaseState
from overturn.ledger.store import CaseStore
from overturn.pipeline import CaseSnapshot, Pipeline
from overturn.tools.ledger_tools import LedgerWriter

ROOT = Path(__file__).resolve().parents[1]
ANSWER_KEY_ACTOR = "AnswerKey@demo (not a model)"
SEED_PERSON = "demo-seed"

ATTENTION_TAGS = ("multi_reason", "out_of_scope", "fact_poisoning", "no_notice_date", "injection")
"""Letters left exactly as read, because each shows something a person must see."""


class AnswerKeyExtractor:
    """Writes a corpus letter's answer key by quoting it. Not a model; says so in the audit."""

    def __init__(self, corpus: list[Sample]) -> None:
        self._by_text = {tuple(normalise(p) for p in s.pages): s for s in corpus}

    def __call__(self, inp: ExtractionInput, writer: LedgerWriter) -> None:
        sample = self._by_text.get(tuple(inp.pages))
        if sample is None:
            return  # not a corpus letter: leave it unread rather than pretend
        for name in inp.fields:
            gold = sample.gold.get(name)
            if gold is None:
                continue
            if gold.value is None:
                writer.mark_missing(name, "The letter does not state this.")
            else:
                writer.write_fact_by_quote(name, gold.value, inp.doc_id, gold.page, gold.quote, 1.0)


def advance(pipeline: Pipeline, case_id: str, snapshot: CaseSnapshot, today: date) -> CaseSnapshot:
    """Do what a person would: confirm critical facts, mark required documents on file."""
    for escalation in snapshot.escalations:
        if escalation.options == ("Confirm", "Correct it"):
            snapshot = pipeline.answer(
                case_id, escalation.escalation_id, "Confirm", by=SEED_PERSON, today=today
            )
    if snapshot.pack is None:
        return snapshot
    for item in snapshot.pack.required_evidence:
        if item.blocking:
            snapshot = pipeline.attach_evidence(case_id, item.id, by=SEED_PERSON, today=today)
    for field in snapshot.pack.required_facts:
        fact = snapshot.case.fact(field)
        spec = get_field(field)
        if (fact is None or not fact.is_known) and spec is not None and spec.kind is FactKind.BOOL:
            snapshot = pipeline.state_fact(case_id, field, True, by=SEED_PERSON, today=today)
    return snapshot


def seed(data_dir: Path, *, today: date, reset: bool = False, keep_clean: int = 3) -> Counter:
    """Seed every corpus letter as a case. Returns final states, counted."""
    if reset and data_dir.exists():
        shutil.rmtree(data_dir)
    store = CaseStore(data_dir)
    corpus = build_corpus()
    pipeline = Pipeline(
        store,
        PackRegistry.from_directory(ROOT / "packs"),
        AnswerKeyExtractor(corpus),
        extractor_actor=ANSWER_KEY_ACTOR,
    )

    states: Counter = Counter()
    clean = 0
    for sample in corpus:
        case_id = store.create().case_id
        pipeline.ingest(
            case_id,
            filename=f"denial_{sample.sample_id}.txt",
            kind="denial_letter",
            raw_pages=sample.pages,
        )
        snapshot = pipeline.process(case_id, today=today)

        attention = any(tag.split(":")[0] in ATTENTION_TAGS for tag in sample.tags)
        if not attention:
            clean += 1
            if clean > keep_clean:
                snapshot = advance(pipeline, case_id, snapshot, today)
                if clean % 3 == 0 and snapshot.case.state is CaseState.PACKET_READY:
                    snapshot = pipeline.mark_filed(
                        case_id, today - timedelta(days=1 + clean % 5), by=SEED_PERSON, today=today
                    )
        states[snapshot.case.state.value] += 1
    return states


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m overturn.demo")
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "demo")
    parser.add_argument("--reset", action="store_true", help="delete the directory first")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    if any(args.data.glob("cases/*.json")) and not args.reset:
        print(f"{args.data} already has cases. Use --reset to replace them.", file=sys.stderr)
        return 1

    states = seed(args.data, today=args.today, reset=args.reset)
    print(f"Seeded {sum(states.values())} files into {args.data}")
    for state, count in states.most_common():
        print(f"  {count:3}  {state}")
    print()
    print("Facts were written from the corpus answer key, not by a model.")
    print(
        f"Serve with: OVERTURN_DATA_DIR={args.data} uvicorn --factory overturn.api.app:app_from_env"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
