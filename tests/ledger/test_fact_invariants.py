"""The guarantees the ledger makes, stated as tests.

If a claim in the README is not exercised here, it is a claim we have not earned. Each
test below corresponds to a sentence we are willing to say out loud about the system.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from overturn.ledger.errors import (
    FactTypeMismatch,
    ProvenanceRequired,
    StatusInvariantViolation,
    UnknownField,
)
from overturn.ledger.schema import (
    ConflictSource,
    Fact,
    FactStatus,
    Provenance,
)

SOURCE = Provenance(
    doc_id="doc_denial_001",
    page=1,
    char_span=(1204, 1256),
    quote="was determined not medically necessary",
)


def make(**overrides) -> Fact:
    """A fact that is valid unless a test deliberately breaks one thing."""
    base = dict(
        field="denial.reason_text",
        value="Service determined not medically necessary",
        status=FactStatus.EXTRACTED,
        confidence=0.94,
        provenance=SOURCE,
        recorded_by="ExtractionAgent@v1",
    )
    base.update(overrides)
    return Fact(**base)


# --- the central guarantee -------------------------------------------------------


def test_a_sourced_value_is_accepted():
    fact = make()
    assert fact.value == "Service determined not medically necessary"
    assert fact.provenance is not None
    assert fact.is_known


def test_a_value_without_a_source_is_refused():
    """The claim: a model cannot record a value it cannot point at."""
    with pytest.raises(ProvenanceRequired):
        make(provenance=None)


def test_human_verified_also_requires_a_source():
    """Verification confirms a source; it does not replace one."""
    with pytest.raises(ProvenanceRequired):
        make(
            status=FactStatus.HUMAN_VERIFIED,
            verified_by="user_004",
            provenance=None,
        )


# --- absence is a recorded state, not an empty key --------------------------------


def test_missing_cannot_carry_a_value():
    with pytest.raises(StatusInvariantViolation):
        make(status=FactStatus.MISSING, value="something plausible", provenance=None)


def test_missing_must_explain_itself():
    """A gap in the interface always says why it is a gap."""
    with pytest.raises(StatusInvariantViolation):
        make(status=FactStatus.MISSING, value=None, provenance=None, reason=None)


def test_missing_with_a_reason_is_valid():
    fact = make(
        field="service.was_urgent",
        status=FactStatus.MISSING,
        value=None,
        provenance=None,
        confidence=None,
        reason="human_judgment_required",
    )
    assert not fact.is_known
    assert fact.reason == "human_judgment_required"


def test_extracted_status_cannot_mean_absent():
    """An absent value must be 'missing', never 'extracted' with nothing in it."""
    with pytest.raises(StatusInvariantViolation):
        make(value=None)


# --- statutory defaults never masquerade as document content ----------------------


def test_regime_default_must_name_its_regime():
    with pytest.raises(StatusInvariantViolation):
        make(
            field="deadline.internal_appeal_due",
            value="2027-01-28",
            status=FactStatus.REGIME_DEFAULT,
            provenance=None,
            regime=None,
        )


def test_regime_default_cannot_claim_a_document_source():
    """If the letter had stated it, it would be 'extracted'. It cannot be both."""
    with pytest.raises(StatusInvariantViolation):
        make(
            field="deadline.internal_appeal_due",
            value="2027-01-28",
            status=FactStatus.REGIME_DEFAULT,
            provenance=SOURCE,
            regime="aca_internal_post_service",
        )


def test_regime_default_is_valid_when_it_names_the_regime():
    fact = make(
        field="deadline.internal_appeal_due",
        value="2027-01-28",
        status=FactStatus.REGIME_DEFAULT,
        provenance=None,
        confidence=None,
        regime="aca_internal_post_service",
        recorded_by="DeadlineEngine@v1",
    )
    assert fact.is_known
    assert fact.regime == "aca_internal_post_service"


# --- conflicts ---------------------------------------------------------------------


def test_conflict_requires_two_sides():
    with pytest.raises(StatusInvariantViolation):
        make(
            field="plan.covers_service",
            value=None,
            status=FactStatus.CONFLICTED,
            provenance=None,
            conflict=[ConflictSource(reads=True, provenance=SOURCE)],
        )


def test_a_two_sided_conflict_is_recorded_not_resolved():
    """The system reports the disagreement; it does not pick a winner."""
    other = Provenance(doc_id="doc_policy_001", page=42, char_span=(10, 40))
    fact = make(
        field="plan.covers_service",
        value=None,
        status=FactStatus.CONFLICTED,
        provenance=None,
        confidence=None,
        conflict=[
            ConflictSource(reads=True, provenance=other),
            ConflictSource(reads=False, provenance=SOURCE),
        ],
    )
    assert fact.value is None
    assert len(fact.conflict) == 2


# --- the taxonomy is a boundary, not documentation ---------------------------------


def test_an_unknown_field_is_refused():
    """Ledger pollution: planted text must not be able to invent a field."""
    with pytest.raises(UnknownField):
        make(field="denial.secret_instruction")


def test_rule_pack_evidence_fields_resolve_dynamically():
    fact = make(
        field="evidence.letter_of_medical_necessity",
        value=True,
        status=FactStatus.EXTRACTED,
    )
    assert fact.value is True


# --- declared value shapes ---------------------------------------------------------


def test_a_date_field_rejects_prose():
    with pytest.raises(FactTypeMismatch):
        make(field="denial.notice_date", value="as soon as possible")


def test_a_date_field_rejects_an_impossible_date():
    with pytest.raises(FactTypeMismatch):
        make(field="denial.notice_date", value="2026-02-30")


def test_a_boolean_field_rejects_a_string():
    with pytest.raises(FactTypeMismatch):
        make(field="service.is_pre_service", value="yes")


def test_a_string_field_rejects_whitespace():
    """An empty string is an absent value wearing a disguise."""
    with pytest.raises(FactTypeMismatch):
        make(field="denial.reason_text", value="   ")


def test_a_list_field_rejects_a_bare_string():
    with pytest.raises(FactTypeMismatch):
        make(field="service.cpt_codes", value="97110")


def test_a_list_field_accepts_codes():
    fact = make(field="service.cpt_codes", value=["97110", "97140"])
    assert fact.value == ["97110", "97140"]


# --- provenance must be usable for highlighting ------------------------------------


def test_a_reversed_span_is_refused():
    with pytest.raises(ValidationError):
        Provenance(doc_id="d", page=1, char_span=(500, 100))


def test_page_numbering_starts_at_one():
    with pytest.raises(ValidationError):
        Provenance(doc_id="d", page=0, char_span=(0, 10))


# --- what may enter a submission packet --------------------------------------------


def test_a_critical_field_is_not_packet_ready_while_only_extracted():
    """Privilege separation stops action, not fact poisoning. This is the containment."""
    fact = make(field="denial.notice_date", value="2026-08-01")
    assert fact.is_known
    assert not fact.is_packet_ready


def test_a_critical_field_is_packet_ready_once_verified():
    fact = make(
        field="denial.notice_date",
        value="2026-08-01",
        status=FactStatus.HUMAN_VERIFIED,
        verified_by="user_004",
    )
    assert fact.is_packet_ready


def test_an_ordinary_field_is_packet_ready_when_sourced():
    assert make().is_packet_ready


def test_nothing_unknown_is_ever_packet_ready():
    fact = make(
        field="service.was_urgent",
        status=FactStatus.MISSING,
        value=None,
        provenance=None,
        confidence=None,
        reason="human_judgment_required",
    )
    assert not fact.is_packet_ready


def test_human_verified_requires_naming_the_verifier():
    with pytest.raises(StatusInvariantViolation):
        make(status=FactStatus.HUMAN_VERIFIED, verified_by=None)


# --- a person's answer is a source of its own -------------------------------------


def test_a_person_can_state_what_no_document_says():
    fact = make(
        field="service.was_urgent",
        value=True,
        status=FactStatus.HUMAN_ANSWERED,
        provenance=None,
        confidence=None,
        verified_by="user_004",
    )
    assert fact.is_known
    assert fact.is_packet_ready


def test_a_human_answer_must_name_who_gave_it():
    with pytest.raises(StatusInvariantViolation):
        make(
            field="service.was_urgent",
            value=True,
            status=FactStatus.HUMAN_ANSWERED,
            provenance=None,
        )


def test_a_person_cannot_state_a_deadline():
    """Deadlines are computed. A person corrects the inputs, never the arithmetic."""
    with pytest.raises(StatusInvariantViolation):
        make(
            field="deadline.internal_appeal_due",
            value="2027-01-28",
            status=FactStatus.HUMAN_ANSWERED,
            provenance=None,
            verified_by="user_004",
        )
