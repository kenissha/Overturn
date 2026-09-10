"""Deadline arithmetic, exhaustively.

A wrong date here loses a file that was winnable. These tests are deliberately dense
around the boundaries: month-end arithmetic, the receipt-versus-notice distinction, and
every case where the honest answer is "cannot compute".
"""

from __future__ import annotations

from datetime import date

import pytest

from overturn.engine.deadlines import (
    Basis,
    Pressure,
    Regime,
    add_months,
    appeal_clock_anchor,
    compute_deadlines,
    select_regime,
)
from overturn.ledger.schema import Case, Fact, FactStatus, Provenance

SOURCE = Provenance(doc_id="doc_denial_001", page=1, char_span=(0, 10), quote="x")


def case_with(**values) -> Case:
    """A case whose facts are already extracted, for exercising the engine alone."""
    case = Case(case_id="case_test")
    for field, value in values.items():
        field = field.replace("__", ".")
        case.facts[field] = Fact(
            field=field,
            value=value,
            status=FactStatus.EXTRACTED,
            provenance=SOURCE,
            confidence=1.0,
            recorded_by="test",
        )
    return case


# --- regime selection ----------------------------------------------------------------


def test_post_service_claim_selects_the_sixty_day_response_regime():
    regime, missing = select_regime(case_with(service__is_pre_service=False))
    assert regime is Regime.ACA_INTERNAL_POST_SERVICE
    assert missing == ()


def test_pre_service_claim_selects_the_thirty_day_response_regime():
    regime, _ = select_regime(case_with(service__is_pre_service=True))
    assert regime is Regime.ACA_INTERNAL_PRE_SERVICE


def test_urgency_overrides_the_pre_post_service_split():
    regime, _ = select_regime(case_with(service__is_pre_service=False, service__was_urgent=True))
    assert regime is Regime.ACA_URGENT


def test_a_final_determination_moves_the_case_to_external_review():
    regime, _ = select_regime(
        case_with(denial__is_final=True, service__is_pre_service=True, service__was_urgent=True)
    )
    assert regime is Regime.ACA_EXTERNAL


def test_an_unclassified_claim_reports_what_it_needs():
    regime, missing = select_regime(case_with(denial__notice_date="2026-08-01"))
    assert regime is None
    assert "service.is_pre_service" in missing


# --- the anchor: receipt beats notice, and absence is safe ---------------------------


def test_receipt_date_is_preferred_over_notice_date():
    anchor = appeal_clock_anchor(
        case_with(denial__notice_date="2026-08-01", denial__received_date="2026-08-06")
    )
    assert anchor.field == "denial.received_date"
    assert anchor.on == date(2026, 8, 6)
    assert not anchor.estimated


def test_notice_date_is_the_fallback_and_is_flagged_as_estimated():
    anchor = appeal_clock_anchor(case_with(denial__notice_date="2026-08-01"))
    assert anchor.field == "denial.notice_date"
    assert anchor.estimated


def test_the_fallback_can_only_shorten_the_window():
    """The safety property, stated directly: guessing must never grant extra days."""
    both = compute_deadlines(
        case_with(
            denial__notice_date="2026-08-01",
            denial__received_date="2026-08-06",
            service__is_pre_service=False,
        )
    )
    notice_only = compute_deadlines(
        case_with(denial__notice_date="2026-08-01", service__is_pre_service=False)
    )

    assert (
        notice_only.get("deadline.internal_appeal_due").due
        <= both.get("deadline.internal_appeal_due").due
    )


def test_no_anchor_means_no_deadline_is_invented():
    result = compute_deadlines(case_with(service__is_pre_service=False))
    assert result.deadlines == ()
    blocked = {b.field: b for b in result.blocked}
    assert "deadline.internal_appeal_due" in blocked
    assert "denial.notice_date" in blocked["deadline.internal_appeal_due"].missing_fields


# --- the filing window ---------------------------------------------------------------


def test_internal_filing_window_is_one_hundred_eighty_days_from_the_anchor():
    result = compute_deadlines(
        case_with(denial__received_date="2026-08-01", service__is_pre_service=False)
    )
    due = result.get("deadline.internal_appeal_due")
    assert due.due == date(2027, 1, 28)
    assert due.basis is Basis.REGIME_DEFAULT


def test_a_date_stated_in_the_letter_overrides_the_statutory_default():
    result = compute_deadlines(
        case_with(
            denial__received_date="2026-08-01",
            denial__stated_appeal_deadline="2026-10-15",
            service__is_pre_service=False,
        )
    )
    due = result.get("deadline.internal_appeal_due")
    assert due.due == date(2026, 10, 15)
    assert due.basis is Basis.STATED_IN_LETTER


def test_a_stated_date_wins_even_when_it_is_longer_than_the_default():
    """Plans may grant more time than the federal floor. We do not clip it."""
    result = compute_deadlines(
        case_with(
            denial__received_date="2026-08-01",
            denial__stated_appeal_deadline="2027-06-01",
            service__is_pre_service=False,
        )
    )
    assert result.get("deadline.internal_appeal_due").due == date(2027, 6, 1)


def test_the_filing_window_is_computed_before_the_claim_is_classified():
    """180 days is common to every internal regime, so classification does not block it."""
    result = compute_deadlines(case_with(denial__received_date="2026-08-01"))

    assert result.regime is None
    assert result.get("deadline.internal_appeal_due").due == date(2027, 1, 28)
    blocked = {b.field for b in result.blocked}
    assert blocked == {"deadline.plan_response_due"}


# --- external review ------------------------------------------------------------------


def test_external_review_runs_four_months_not_one_hundred_twenty_days():
    result = compute_deadlines(case_with(denial__is_final=True, denial__received_date="2026-08-01"))
    due = result.get("deadline.external_review_due")
    assert due.due == date(2026, 12, 1)
    assert due.regime is Regime.ACA_EXTERNAL


def test_external_review_does_not_produce_an_internal_appeal_deadline():
    result = compute_deadlines(case_with(denial__is_final=True, denial__received_date="2026-08-01"))
    assert result.get("deadline.internal_appeal_due") is None


# --- the plan's response window --------------------------------------------------------


def test_the_response_window_waits_for_a_filing_date():
    result = compute_deadlines(
        case_with(denial__received_date="2026-08-01", service__is_pre_service=False)
    )
    blocked = {b.field: b for b in result.blocked}
    assert blocked["deadline.plan_response_due"].missing_fields == ("appeal.filed_date",)


def test_post_service_response_window_is_sixty_days_from_filing():
    case = case_with(denial__received_date="2026-08-01", service__is_pre_service=False)
    case.facts["appeal.filed_date"] = Fact(
        field="appeal.filed_date",
        value="2026-09-01",
        status=FactStatus.HUMAN_VERIFIED,
        provenance=SOURCE,
        verified_by="user_004",
        recorded_by="user_004",
    )
    assert compute_deadlines(case).get("deadline.plan_response_due").due == date(2026, 10, 31)


def test_pre_service_response_window_is_thirty_days_from_filing():
    case = case_with(denial__received_date="2026-08-01", service__is_pre_service=True)
    case.facts["appeal.filed_date"] = Fact(
        field="appeal.filed_date",
        value="2026-09-01",
        status=FactStatus.HUMAN_VERIFIED,
        provenance=SOURCE,
        verified_by="user_004",
        recorded_by="user_004",
    )
    assert compute_deadlines(case).get("deadline.plan_response_due").due == date(2026, 10, 1)


def test_an_urgent_claim_is_tracked_in_hours_not_as_a_calendar_date():
    case = case_with(denial__received_date="2026-08-01", service__was_urgent=True)
    result = compute_deadlines(case)
    blocked = {b.field: b for b in result.blocked}
    assert "72" in blocked["deadline.plan_response_due"].explanation


# --- month arithmetic -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, date(2028, 2, 29)),  # leap year
        (date(2026, 10, 31), 4, date(2027, 2, 28)),
        (date(2026, 8, 31), 4, date(2026, 12, 31)),
        (date(2026, 9, 30), 4, date(2027, 1, 30)),
        (date(2026, 12, 15), 4, date(2027, 4, 15)),
    ],
)
def test_month_addition_clamps_to_the_end_of_the_month(start, months, expected):
    """Rolling into the next month would hand the advocate days they do not have."""
    assert add_months(start, months) == expected


# --- pressure bands ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 1, 1), Pressure.NONE),
        (date(2026, 12, 29), Pressure.INFO),  # 30 days out
        (date(2027, 1, 14), Pressure.ELEVATED),  # 14
        (date(2027, 1, 21), Pressure.URGENT),  # 7
        (date(2027, 1, 25), Pressure.CRITICAL),  # 3
        (date(2027, 1, 28), Pressure.CRITICAL),  # due today
        (date(2027, 1, 29), Pressure.EXPIRED),
    ],
)
def test_pressure_bands(today, expected):
    result = compute_deadlines(
        case_with(denial__received_date="2026-08-01", service__is_pre_service=False)
    )
    assert result.get("deadline.internal_appeal_due").pressure(today) is expected


def test_only_the_upper_bands_escalate():
    """T-30 is visible in the interface but does not interrupt anyone."""
    assert not Pressure.NONE.escalates
    assert not Pressure.INFO.escalates
    assert Pressure.ELEVATED.escalates
    assert Pressure.URGENT.escalates
    assert Pressure.CRITICAL.escalates
    assert Pressure.EXPIRED.escalates


def test_recording_the_filing_meets_the_filing_window():
    case = case_with(denial__received_date="2026-08-01", service__is_pre_service=False)
    case.facts["appeal.filed_date"] = Fact(
        field="appeal.filed_date",
        value="2027-01-20",
        status=FactStatus.HUMAN_ANSWERED,
        verified_by="user_004",
        recorded_by="user_004",
    )
    result = compute_deadlines(case)
    filing = result.get("deadline.internal_appeal_due")
    assert filing.met_on == date(2027, 1, 20)
    assert filing.pressure(date(2027, 1, 27)) is Pressure.NONE
    assert result.get("deadline.plan_response_due").met_on is None
