"""What the case still needs, and what may go out.

The behaviour worth pinning down here is the distinction between a fact that is absent and
a fact that is present, correctly sourced, and still not enough.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from overturn.engine.evidence import assess
from overturn.engine.packs import PackRegistry
from overturn.ledger.schema import (
    Case,
    ConflictSource,
    Fact,
    FactStatus,
    Provenance,
)

PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"
SOURCE = Provenance(doc_id="doc_denial_001", page=1, char_span=(0, 10), quote="x")
OTHER_SOURCE = Provenance(doc_id="doc_policy_001", page=42, char_span=(0, 10), quote="y")


@pytest.fixture(scope="module")
def pack():
    return PackRegistry.from_directory(PACKS_DIR).get("medical_necessity")


def extracted(case: Case, field: str, value) -> None:
    case.facts[field] = Fact(
        field=field,
        value=value,
        status=FactStatus.EXTRACTED,
        confidence=0.95,
        provenance=SOURCE,
        recorded_by="test",
    )


def verified(case: Case, field: str, value) -> None:
    case.facts[field] = Fact(
        field=field,
        value=value,
        status=FactStatus.HUMAN_VERIFIED,
        provenance=SOURCE,
        verified_by="user_004",
        recorded_by="user_004",
    )


def fully_stocked_case(pack) -> Case:
    """Every required fact verified and every blocking document on file."""
    case = Case(case_id="case_test")
    verified(case, "denial.notice_date", "2026-08-01")
    extracted(case, "denial.cited_policy_section", "Section 4.2(b)")
    extracted(case, "service.description", "Lumbar MRI")
    extracted(case, "service.date_of_service", "2026-07-14")
    verified(case, "service.is_pre_service", False)
    extracted(case, "provider.is_treating_physician", True)
    for item in pack.required_evidence:
        extracted(case, item.fact_field, True)
    return case


# --- readiness --------------------------------------------------------------------


def test_a_fully_stocked_case_is_packet_ready(pack):
    readiness = assess(fully_stocked_case(pack), pack)
    assert readiness.is_packet_ready
    assert readiness.blocking_count == 0
    assert "Packet ready" in readiness.summary()


def test_a_missing_blocking_document_holds_the_packet(pack):
    case = fully_stocked_case(pack)
    del case.facts["evidence.clinical_notes"]

    readiness = assess(case, pack)
    assert not readiness.is_packet_ready
    assert [i.id for i in readiness.missing_blocking_evidence] == ["clinical_notes"]


def test_a_missing_optional_document_does_not_hold_the_packet(pack):
    case = fully_stocked_case(pack)
    del case.facts["evidence.relevant_guideline"]

    readiness = assess(case, pack)
    assert readiness.is_packet_ready
    assert [i.id for i in readiness.missing_optional_evidence] == ["relevant_guideline"]


def test_evidence_recorded_as_absent_counts_as_missing(pack):
    """A document explicitly marked not-on-file is missing, not present."""
    case = fully_stocked_case(pack)
    extracted(case, "evidence.clinical_notes", False)

    readiness = assess(case, pack)
    assert not readiness.is_packet_ready
    assert [i.id for i in readiness.missing_blocking_evidence] == ["clinical_notes"]


# --- what only a person can supply --------------------------------------------------


def test_a_document_only_a_human_can_obtain_is_reported_separately(pack):
    """Escalation trigger 1: no agent can produce a physician's letter."""
    case = fully_stocked_case(pack)
    del case.facts["evidence.letter_of_medical_necessity"]

    readiness = assess(case, pack)
    gaps = [i.id for i in readiness.human_only_gaps]
    assert gaps == ["letter_of_medical_necessity"]


def test_ordinary_missing_documents_are_not_reported_as_human_only(pack):
    case = fully_stocked_case(pack)
    del case.facts["evidence.clinical_notes"]

    assert assess(case, pack).human_only_gaps == ()


# --- sourced is not the same as sufficient --------------------------------------------


def test_a_critical_fact_that_is_only_extracted_holds_the_packet(pack):
    """The containment for fact poisoning, in the place it actually bites."""
    case = fully_stocked_case(pack)
    extracted(case, "denial.notice_date", "2026-08-01")  # downgrade from verified

    readiness = assess(case, pack)
    assert not readiness.is_packet_ready
    assert "denial.notice_date" in readiness.unverified_critical_facts
    # It is not missing: it is known, sourced, and awaiting a person.
    assert "denial.notice_date" not in [g.field for g in readiness.fact_gaps]


def test_an_ordinary_fact_needs_no_verification(pack):
    case = fully_stocked_case(pack)
    extracted(case, "service.description", "Lumbar MRI")

    assert assess(case, pack).is_packet_ready


def test_verifying_the_critical_fact_clears_the_block(pack):
    case = fully_stocked_case(pack)
    extracted(case, "denial.notice_date", "2026-08-01")
    assert not assess(case, pack).is_packet_ready

    verified(case, "denial.notice_date", "2026-08-01")
    assert assess(case, pack).is_packet_ready


# --- gaps explain themselves -----------------------------------------------------------


def test_a_fact_never_looked_for_is_distinguished_from_one_searched_and_not_found(pack):
    case = fully_stocked_case(pack)
    del case.facts["service.description"]
    case.facts["denial.cited_policy_section"] = Fact(
        field="denial.cited_policy_section",
        value=None,
        status=FactStatus.MISSING,
        reason="the letter refers to a section but does not name it",
        recorded_by="test",
    )

    gaps = {g.field: g for g in assess(case, pack).fact_gaps}

    assert gaps["service.description"].status is None
    assert "Not yet looked for" in gaps["service.description"].reason
    assert gaps["denial.cited_policy_section"].status is FactStatus.MISSING
    assert "does not name it" in gaps["denial.cited_policy_section"].reason


def test_a_conflict_is_reported_as_a_conflict_not_as_absence(pack):
    case = fully_stocked_case(pack)
    case.facts["service.is_pre_service"] = Fact(
        field="service.is_pre_service",
        value=None,
        status=FactStatus.CONFLICTED,
        conflict=[
            ConflictSource(reads=True, provenance=SOURCE),
            ConflictSource(reads=False, provenance=OTHER_SOURCE),
        ],
        recorded_by="test",
    )

    readiness = assess(case, pack)
    assert not readiness.is_packet_ready
    assert [g.field for g in readiness.conflicts] == ["service.is_pre_service"]
    assert "may be an argument" in readiness.conflicts[0].reason


def test_the_summary_counts_each_kind_of_block_separately(pack):
    case = fully_stocked_case(pack)
    del case.facts["evidence.clinical_notes"]
    del case.facts["service.description"]
    extracted(case, "denial.notice_date", "2026-08-01")

    summary = assess(case, pack).summary()
    assert "1 required document(s) not on file" in summary
    assert "1 required fact(s) unresolved" in summary
    assert "1 critical fact(s) unverified" in summary
