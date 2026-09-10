"""Classification: the branch point for everything downstream.

The behaviour under test is not only "does it pick the right pack" but "does it decline
when it should". A confident wrong classification produces an appeal that argues against a
reason the letter never gave, which is one of the ways these files are lost.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from overturn.engine.packs import PackRegistry
from overturn.engine.rules import classify
from overturn.ledger.schema import Case, Fact, FactStatus, Provenance

PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"
SOURCE = Provenance(doc_id="doc_denial_001", page=1, char_span=(0, 10), quote="x")


@pytest.fixture(scope="module")
def registry() -> PackRegistry:
    return PackRegistry.from_directory(PACKS_DIR)


def case_with(**values) -> Case:
    case = Case(case_id="case_test")
    for key, value in values.items():
        field = key.replace("__", ".")
        confidence = 1.0
        if isinstance(value, tuple):
            value, confidence = value
        case.facts[field] = Fact(
            field=field,
            value=value,
            status=FactStatus.EXTRACTED,
            confidence=confidence,
            provenance=SOURCE,
            recorded_by="test",
        )
    return case


# --- recognising a category ----------------------------------------------------------


def test_a_reason_code_selects_the_pack(registry):
    result = classify(case_with(denial__reason_code="CO-50"), registry)
    assert result.selected.id == "medical_necessity"
    assert not result.ambiguous


def test_a_phrase_selects_the_pack(registry):
    result = classify(
        case_with(
            denial__reason_text="Service was determined not medically necessary under 4.2(b)."
        ),
        registry,
    )
    assert result.selected.id == "medical_necessity"


def test_phrase_matching_ignores_case_and_spacing(registry):
    result = classify(
        case_with(denial__reason_text="NOT   MEDICALLY\nNECESSARY per review"), registry
    )
    assert result.selected.id == "medical_necessity"


def test_prior_authorization_is_recognised(registry):
    result = classify(
        case_with(denial__reason_text="No prior authorization was obtained for this service."),
        registry,
    )
    assert result.selected.id == "prior_authorization"


# --- it explains itself ----------------------------------------------------------------


def test_the_decision_carries_the_signal_that_produced_it(registry):
    result = classify(case_with(denial__reason_code="CO-197"), registry)
    assert result.selected.id == "prior_authorization"
    assert "CO-197" in result.explanation
    assert "denial.reason_code" in result.explanation


def test_the_signal_points_at_the_page_it_came_from(registry):
    result = classify(case_with(denial__reason_code="CO-50"), registry)
    signal = result.candidates[0].signals[0]
    assert signal.doc_id == "doc_denial_001"
    assert signal.page == 1


def test_a_reason_code_outranks_a_phrase(registry):
    """Codes are exact; phrasing is paraphrasable. Corroboration never inverts that."""
    result = classify(
        case_with(
            denial__reason_code="CO-197",
            denial__reason_text="not medically necessary and not medically appropriate",
        ),
        registry,
    )
    top, second = result.candidates[0], result.candidates[1]
    assert top.pack.id == "prior_authorization"
    assert second.pack.id == "medical_necessity"


# --- it declines when it should ----------------------------------------------------------


def test_a_letter_citing_two_categories_is_not_silently_resolved(registry):
    """A denial naming two reasons is a trap, not a tie to be broken by score."""
    result = classify(
        case_with(
            denial__reason_text=(
                "The service was determined not medically necessary. Additionally, no "
                "prior authorization was obtained."
            )
        ),
        registry,
    )
    assert result.selected is None
    assert result.ambiguous
    assert result.needs_human
    assert len(result.candidates) == 2


def test_an_unreadable_denial_reason_blocks_classification(registry):
    result = classify(case_with(denial__notice_date="2026-08-01"), registry)
    assert result.selected is None
    assert not result.ambiguous
    assert "denial.reason_text" in result.blocked_by


def test_a_category_outside_the_installed_packs_is_reported_as_such(registry):
    """Saying 'this is outside what I cover' beats forcing the nearest fit."""
    result = classify(
        case_with(denial__reason_text="Coordination of benefits: other coverage is primary."),
        registry,
    )
    assert result.selected is None
    assert not result.ambiguous
    assert result.candidates == ()
    assert "does not match any rule pack" in result.explanation


def test_a_missing_fact_is_not_matched_against(registry):
    case = Case(case_id="case_test")
    case.facts["denial.reason_text"] = Fact(
        field="denial.reason_text",
        value=None,
        status=FactStatus.MISSING,
        reason="letter states a reason code but no prose reason",
        recorded_by="test",
    )
    result = classify(case, registry)
    assert result.selected is None
    assert "denial.reason_text" in result.blocked_by


def test_a_reading_below_the_pack_confidence_threshold_is_treated_as_absent(registry):
    """Classification branches the whole pipeline; it does not build on a weak reading."""
    result = classify(case_with(denial__reason_text=("not medically necessary", 0.40)), registry)
    assert result.selected is None
    assert result.candidates == ()


# --- the full set of packs -------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "pack_id"),
    [
        ("The provider is not a participating provider in your plan.", "out_of_network"),
        ("Services were rendered by an out-of-network provider.", "out_of_network"),
        ("The claim was denied due to a billing error.", "coding_error"),
        ("The diagnosis is inconsistent with the procedure billed.", "coding_error"),
        ("The requested treatment is considered experimental.", "experimental"),
        ("This therapy is investigational for your condition.", "experimental"),
    ],
)
def test_each_category_is_recognised_by_its_phrasing(registry, reason, pack_id):
    result = classify(case_with(denial__reason_text=reason), registry)
    assert result.selected is not None, result.explanation
    assert result.selected.id == pack_id


@pytest.mark.parametrize(
    ("code", "pack_id"),
    [
        ("CO-242", "out_of_network"),
        ("CO-16", "coding_error"),
        ("CO-55", "experimental"),
    ],
)
def test_each_category_is_recognised_by_its_reason_code(registry, code, pack_id):
    assert classify(case_with(denial__reason_code=code), registry).selected.id == pack_id


def test_an_experimental_code_is_not_filed_as_medical_necessity(registry):
    """CO-55 once sat in the medical necessity pack. Appealing necessity when the plan
    said 'experimental' answers a reason the plan did not give."""
    assert classify(case_with(denial__reason_code="CO-55"), registry).selected.id != (
        "medical_necessity"
    )


def test_a_diagnosis_exclusion_is_not_forced_into_a_category(registry):
    result = classify(case_with(denial__reason_code="CO-167"), registry)
    assert result.selected is None
    assert result.candidates == ()


def test_a_deactivated_reason_code_is_not_relied_on(registry):
    """CO-15 was deactivated by X12 in 2018. A letter printing it is classified by its
    wording, not by a code that no longer means anything."""
    assert classify(case_with(denial__reason_code="CO-15"), registry).selected is None
    worded = case_with(
        denial__reason_code="CO-15",
        denial__reason_text="there is no authorization on file for this service",
    )
    assert classify(worded, registry).selected.id == "prior_authorization"
