"""Retention: finished files go after the period; open files never do."""

from __future__ import annotations

from datetime import timedelta

import pytest

from overturn.ledger.schema import CaseState, utcnow
from overturn.ledger.store import CaseStore
from overturn.retention import purge_finished, retention_days_from_env


def make_case(store: CaseStore, state: CaseState, age_days: int) -> str:
    case = store.create()
    case.state = state
    case.updated_at = utcnow() - timedelta(days=age_days)
    # Written directly: CaseStore.save would stamp updated_at with the current time.
    store.path_for(case.case_id).write_text(case.model_dump_json(), encoding="utf-8")
    store.record_write(case.case_id, actor="t", field="denial.notice_date", outcome="accepted")
    store.save_document_text(case.case_id, "doc_x", raw_pages=["x"], pages=["x"], anomalies=[])
    return case.case_id


def test_a_finished_file_past_the_period_is_removed_entirely(tmp_path):
    store = CaseStore(tmp_path)
    case_id = make_case(store, CaseState.RESOLVED_OVERTURNED, age_days=40)

    report = purge_finished(store, older_than_days=30)

    assert report.purged == [case_id]
    assert not store.path_for(case_id).exists()
    assert not store.audit_path(case_id).exists()
    assert not (tmp_path / "texts" / case_id).exists()


def test_an_open_file_is_never_purged_however_old(tmp_path):
    store = CaseStore(tmp_path)
    make_case(store, CaseState.AWAITING_DOCUMENT, age_days=900)
    make_case(store, CaseState.EXTERNAL_REVIEW_ELIGIBLE, age_days=900)

    report = purge_finished(store, older_than_days=30)
    assert report.purged == []
    assert report.kept_open == 2


def test_a_recently_finished_file_is_kept(tmp_path):
    store = CaseStore(tmp_path)
    make_case(store, CaseState.RESOLVED_UPHELD, age_days=5)
    assert purge_finished(store, older_than_days=30).kept_recent == 1


def test_a_dry_run_removes_nothing(tmp_path):
    store = CaseStore(tmp_path)
    case_id = make_case(store, CaseState.CLOSED_DEADLINE_MISSED, age_days=40)

    report = purge_finished(store, older_than_days=30, dry_run=True)
    assert report.purged == [case_id]
    assert store.path_for(case_id).exists()


def test_retention_is_off_unless_configured():
    assert retention_days_from_env({}) is None
    assert retention_days_from_env({"OVERTURN_RETENTION_DAYS": "14"}) == 14
    with pytest.raises(ValueError):
        retention_days_from_env({"OVERTURN_RETENTION_DAYS": "0"})
