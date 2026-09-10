"""Deterministic conversion between what a model says and what the ledger holds."""

from __future__ import annotations

import pytest

from overturn.ledger.errors import FactTypeMismatch, UnknownField
from overturn.tools.quoting import coerce_value, locate_quote, parse_date

PAGE = (
    "Date of notice: August 1, 2026\n"
    "We have denied this request because the requested service was\n"
    "determined not medically necessary, under Section 4.2(b)."
)


# --- locating quotes ------------------------------------------------------------------


def test_an_exact_quote_is_found():
    start, end = locate_quote(PAGE, "Section 4.2(b)")
    assert PAGE[start:end] == "Section 4.2(b)"


def test_a_quote_spanning_a_line_break_is_found():
    start, end = locate_quote(PAGE, "the requested service was determined not medically necessary")
    assert "was\ndetermined" in PAGE[start:end]


def test_case_differences_are_tolerated():
    assert locate_quote(PAGE, "SECTION 4.2(B)") is not None


def test_regex_characters_in_a_quote_are_literal():
    """Parentheses and dots in a policy section must not become a pattern."""
    assert locate_quote(PAGE, "4.2(b)") is not None
    assert locate_quote(PAGE, "4x2(b)") is None


def test_a_paraphrase_is_not_found():
    assert locate_quote(PAGE, "the service was not medically needed") is None


def test_an_empty_quote_is_never_found():
    assert locate_quote(PAGE, "   ") is None


# --- converting values ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "iso"),
    [
        ("2026-08-01", "2026-08-01"),
        ("08/01/2026", "2026-08-01"),
        ("8/1/2026", "2026-08-01"),
        ("August 1, 2026", "2026-08-01"),
        ("Aug. 1, 2026", "2026-08-01"),
        ("Sept 30, 2026", "2026-09-30"),
        ("1 August 2026", "2026-08-01"),
        ("August 1 2026", "2026-08-01"),
    ],
)
def test_the_date_formats_notices_print(printed, iso):
    assert parse_date("denial.notice_date", printed) == iso


def test_slash_dates_are_read_month_first():
    """US correspondence. 03/04/2026 is March 4th, not April 3rd."""
    assert parse_date("denial.notice_date", "03/04/2026") == "2026-03-04"


@pytest.mark.parametrize("bad", ["February 30, 2026", "13/01/2026", "soon", "within 180 days"])
def test_non_dates_are_refused(bad):
    with pytest.raises(FactTypeMismatch):
        parse_date("denial.notice_date", bad)


@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("Yes", True), ("no", False)])
def test_booleans(raw, expected):
    assert coerce_value("service.is_pre_service", raw) is expected


def test_an_ambiguous_boolean_is_refused():
    with pytest.raises(FactTypeMismatch):
        coerce_value("service.is_pre_service", "probably")


def test_code_lists_split_on_commas_and_semicolons():
    assert coerce_value("service.cpt_codes", "97110, 97140; 97530") == ["97110", "97140", "97530"]


def test_text_is_trimmed_but_otherwise_kept():
    assert coerce_value("denial.reason_text", "  not medically necessary ") == (
        "not medically necessary"
    )


def test_typed_values_pass_through():
    assert coerce_value("service.is_pre_service", True) is True


def test_an_unknown_field_is_refused_before_conversion():
    with pytest.raises(UnknownField):
        coerce_value("denial.invented", "x")
