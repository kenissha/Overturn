"""The background tick: files move forward, and a question is surfaced once."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from overturn.engine.packs import PackRegistry
from overturn.eval.corpus import build_corpus
from overturn.eval.harness import OracleExtractor
from overturn.ledger.store import CaseStore
from overturn.pipeline import Pipeline
from overturn.scheduler import Scheduler

PACKS_DIR = Path(__file__).resolve().parents[1] / "packs"
TODAY = date(2026, 9, 10)


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


@pytest.fixture
def pipeline(tmp_path, corpus):
    return Pipeline(
        CaseStore(tmp_path), PackRegistry.from_directory(PACKS_DIR), OracleExtractor(corpus)
    )


def open_letter(pipeline, corpus) -> str:
    sample = next(
        s
        for s in corpus
        if s.expected_pack == "medical_necessity"
        and s.is_clean
        and s.gold["denial.notice_date"].value
    )
    case_id = pipeline.store.create().case_id
    pipeline.ingest(
        case_id,
        filename="letter.txt",
        kind="denial_letter",
        raw_pages=sample.pages,
        doc_id=sample.doc_id,
    )
    return case_id


def test_a_tick_reads_what_is_unread_and_surfaces_its_questions(pipeline, corpus):
    open_letter(pipeline, corpus)
    report = Scheduler(pipeline).tick(today=TODAY)
    assert report.cases == 1
    assert report.documents_read == 1
    assert report.new_questions
    assert report.open_questions == len(report.new_questions)


def test_a_second_tick_on_an_unchanged_file_reads_nothing_and_raises_nothing_new(pipeline, corpus):
    open_letter(pipeline, corpus)
    scheduler = Scheduler(pipeline)
    first = scheduler.tick(today=TODAY)
    second = scheduler.tick(today=TODAY)
    assert second.documents_read == 0
    assert second.new_questions == []
    assert second.open_questions == first.open_questions


def test_a_deadline_crossing_overnight_is_a_new_question(pipeline, corpus):
    case_id = open_letter(pipeline, corpus)
    scheduler = Scheduler(pipeline)
    scheduler.tick(today=TODAY)

    due = pipeline.evaluate(case_id, today=TODAY).deadlines.get("deadline.internal_appeal_due").due
    later = scheduler.tick(today=due - timedelta(days=5))
    assert any("days away" in question for _, question in later.new_questions)


def test_what_has_been_surfaced_survives_a_restart(pipeline, corpus):
    open_letter(pipeline, corpus)
    Scheduler(pipeline).tick(today=TODAY)
    assert Scheduler(pipeline).tick(today=TODAY).new_questions == []
