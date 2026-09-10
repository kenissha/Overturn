"""The drafting contract: the appeal says only what the ledger supports.

The behaviour worth defending is omission. A paragraph that cannot be backed is left out
and reported, rather than softened into a vaguer claim — so these tests check what is
absent from the letter as carefully as what is present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from overturn.engine.argument import plan_argument, render_letter
from overturn.engine.packs import PackRegistry, RulePack
from overturn.ledger.schema import (
    Case,
    ConflictSource,
    Fact,
    FactStatus,
    Provenance,
)

PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"
SOURCE = Provenance(doc_id="doc_denial_001", page=1, char_span=(0, 10), quote="x")
POLICY = Provenance(doc_id="doc_policy_001", page=42, char_span=(0, 10), quote="y")


@pytest.fixture(scope="module")
def registry():
    return PackRegistry.from_directory(PACKS_DIR)


@pytest.fixture(scope="module")
def pack(registry):
    return registry.get("medical_necessity")


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


def complete_case(pack) -> Case:
    case = Case(case_id="case_test")
    verified(case, "denial.notice_date", "2026-08-01")
    extracted(case, "denial.cited_policy_section", "Section 4.2(b)")
    extracted(case, "service.description", "Lumbar MRI")
    extracted(case, "service.date_of_service", "2026-07-14")
    verified(case, "service.is_pre_service", False)
    extracted(case, "provider.is_treating_physician", True)
    extracted(case, "plan.issuer", "Harborline Health Plan")
    for item in pack.required_evidence:
        extracted(case, item.fact_field, True)
    return case


# --- what is written -------------------------------------------------------------------


def test_every_unconditional_step_is_written_on_a_complete_case(pack):
    plan = plan_argument(complete_case(pack), pack)
    assert [s.step_id for s in plan.included] == [
        "opening",
        "standard_challenge",
        "necessity_argument",
        "clinical_support",
        "conservative_treatment",
        "guideline_support",
    ]
    assert plan.gaps == ()


def test_placeholders_are_filled_from_the_ledger(pack):
    opening = plan_argument(complete_case(pack), pack).step("opening")
    assert "Lumbar MRI" in opening.text
    assert "August 1, 2026" in opening.text


def test_no_placeholder_survives_into_the_letter(pack):
    case = complete_case(pack)
    letter = render_letter(plan_argument(case, pack), case)
    assert "{" not in letter and "}" not in letter


def test_each_paragraph_cites_the_facts_it_was_built_from(pack):
    opening = plan_argument(complete_case(pack), pack).step("opening")
    cited = {c.field: c for c in opening.citations}
    assert set(cited) == {"service.description", "denial.notice_date"}
    assert cited["denial.notice_date"].provenance.doc_id == "doc_denial_001"


# --- what is not written ------------------------------------------------------------------


def test_missing_evidence_omits_the_paragraph_it_supports(pack):
    case = complete_case(pack)
    del case.facts["evidence.letter_of_medical_necessity"]

    plan = plan_argument(case, pack)
    gap = next(s for s in plan.gaps if s.step_id == "necessity_argument")
    assert gap.missing_evidence == ("letter_of_medical_necessity",)
    assert "documented the medical necessity" not in render_letter(plan, case)


def test_a_missing_fact_omits_the_claim_rather_than_softening_it(pack):
    """No 'the denial relies on a section of your plan'. Either the section or nothing."""
    case = complete_case(pack)
    case.facts["denial.cited_policy_section"] = Fact(
        field="denial.cited_policy_section",
        status=FactStatus.MISSING,
        reason="letter cites the plan generally",
        recorded_by="test",
    )

    plan = plan_argument(case, pack)
    gap = next(s for s in plan.gaps if s.step_id == "standard_challenge")
    assert gap.missing_facts == ("denial.cited_policy_section",)
    assert "relies on" not in render_letter(plan, case)


def test_an_omission_explains_itself_in_plain_terms(pack):
    case = complete_case(pack)
    del case.facts["evidence.clinical_notes"]
    gap = next(s for s in plan_argument(case, pack).gaps if s.step_id == "clinical_support")
    assert "Clinical notes covering the date of service" in gap.reason


# --- conditional steps -----------------------------------------------------------------------


def test_a_conditional_paragraph_is_absent_when_its_condition_does_not_hold(pack):
    plan = plan_argument(complete_case(pack), pack)
    skipped = next(s for s in plan.omitted if s.step_id == "policy_conflict")
    assert skipped.condition_unmet
    assert not skipped.is_gap


def test_a_conditional_paragraph_appears_when_its_condition_holds(pack):
    case = complete_case(pack)
    case.facts["plan.covers_service"] = Fact(
        field="plan.covers_service",
        status=FactStatus.CONFLICTED,
        conflict=[
            ConflictSource(reads=True, provenance=POLICY),
            ConflictSource(reads=False, provenance=SOURCE),
        ],
        recorded_by="test",
    )
    assert plan_argument(case, pack).step("policy_conflict") is not None


def test_a_value_condition_gates_the_prior_authorization_argument(registry):
    pack = registry.get("prior_authorization")
    case = Case(case_id="case_test")
    extracted(case, "service.description", "Knee arthroscopy")
    extracted(case, "service.date_of_service", "2026-07-14")
    extracted(case, "evidence.authorization_record", True)

    extracted(case, "service.was_prior_auth_obtained", True)
    assert plan_argument(case, pack).step("authorization_was_obtained") is not None

    extracted(case, "service.was_prior_auth_obtained", False)
    assert plan_argument(case, pack).step("authorization_was_obtained") is None


# --- verification is visible, not hidden -------------------------------------------------------


def test_a_paragraph_resting_on_an_unverified_critical_fact_is_flagged(pack):
    case = complete_case(pack)
    extracted(case, "denial.notice_date", "2026-08-01")
    assert plan_argument(case, pack).step("opening").rests_on_unverified


def test_a_paragraph_on_verified_facts_is_not_flagged(pack):
    assert not plan_argument(complete_case(pack), pack).step("opening").rests_on_unverified


# --- the assembled letter -------------------------------------------------------------------------


def test_the_letter_says_on_its_face_that_it_has_not_been_sent(pack):
    case = complete_case(pack)
    assert "has not been sent" in render_letter(plan_argument(case, pack), case)


def test_enclosures_list_only_documents_a_written_paragraph_relies_on(pack):
    case = complete_case(pack)
    del case.facts["evidence.relevant_guideline"]
    letter = render_letter(plan_argument(case, pack), case)
    assert "Letter of medical necessity from the treating physician" in letter
    assert "Applicable clinical guideline" not in letter


def test_an_unlisted_placeholder_is_still_required():
    """A pack author who forgets requires_facts does not get a sentence with a hole."""
    pack = RulePack.model_validate(
        {
            "id": "t",
            "version": "1",
            "display_name": "T",
            "match": {"any_of": [{"phrase_matches": ["x"]}]},
            "argument_skeleton": [{"id": "opening", "claim": "About {service.description}."}],
        }
    )
    plan = plan_argument(Case(case_id="case_test"), pack)
    assert plan.included == ()
    assert plan.gaps[0].missing_facts == ("service.description",)
