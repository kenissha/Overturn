"""A denial file, end to end, through the real pipeline.

Extraction here is the calibration oracle — it writes the answer key through the real
ledger tools — so these tests exercise everything after reading: classification, gaps,
deadlines, the escalation gate, the state machine, and the points where a person acts.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from overturn.engine.escalation import Trigger
from overturn.engine.packs import PackRegistry
from overturn.eval.corpus import build_corpus
from overturn.eval.harness import OracleExtractor
from overturn.ledger.errors import StatusInvariantViolation
from overturn.ledger.schema import CaseState, FactStatus
from overturn.ledger.store import CaseStore
from overturn.pipeline import Pipeline

PACKS_DIR = Path(__file__).resolve().parents[1] / "packs"
TODAY = date(2026, 9, 10)
ADVOCATE = "user_004"


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


@pytest.fixture(scope="module")
def registry():
    return PackRegistry.from_directory(PACKS_DIR)


@pytest.fixture
def pipeline(tmp_path, registry, corpus):
    return Pipeline(CaseStore(tmp_path), registry, OracleExtractor(corpus))


def open_with(pipeline, sample) -> str:
    case = pipeline.store.create()
    pipeline.ingest(
        case.case_id,
        filename=f"{sample.sample_id}.txt",
        kind="denial_letter",
        raw_pages=sample.pages,
        doc_id=sample.doc_id,
    )
    return case.case_id


def medical_necessity_letter(corpus):
    return next(
        s
        for s in corpus
        if s.expected_pack == "medical_necessity"
        and s.is_clean
        and s.gold["denial.cited_policy_section"].value
        and s.gold["denial.notice_date"].value
    )


def verify_escalations(snapshot):
    return [e for e in snapshot.escalations if e.options == ("Confirm", "Correct it")]


# --- before and after reading -------------------------------------------------------------


def test_an_unread_case_waits_at_intake(pipeline, corpus):
    case_id = open_with(pipeline, medical_necessity_letter(corpus))
    snapshot = pipeline.evaluate(case_id, today=TODAY)
    assert snapshot.case.state is CaseState.INTAKE
    assert snapshot.pack is None
    assert "denial.reason_text" in snapshot.classification.blocked_by


def test_ingest_keeps_normalised_text_and_what_normalisation_removed(pipeline, corpus):
    sample = next(s for s in corpus if "injection:hidden" in s.tags)
    case_id = open_with(pipeline, sample)
    stored = pipeline.store.load_document_text(case_id, sample.doc_id)
    assert stored["raw_pages"] == sample.pages
    assert chr(0x200B) not in "".join(stored["pages"])
    kinds = {a.kind.value for a in pipeline.anomalies(pipeline.store.load(case_id))}
    assert "hidden_text" in kinds


def test_reading_a_letter_classifies_it_and_raises_only_what_needs_a_person(pipeline, corpus):
    case_id = open_with(pipeline, medical_necessity_letter(corpus))
    snapshot = pipeline.process(case_id, today=TODAY)

    assert snapshot.pack.id == "medical_necessity"
    assert snapshot.case.state is CaseState.AWAITING_DOCUMENT
    triggers = {e.trigger for e in snapshot.escalations}
    assert Trigger.HUMAN_ONLY_DOCUMENT in triggers  # the physician's letter
    assert Trigger.HUMAN_JUDGMENT in triggers  # critical facts to confirm
    assert Trigger.DEADLINE_PRESSURE not in triggers  # months away
    assert snapshot.case.history[-1].to_state is CaseState.AWAITING_DOCUMENT


def test_processing_again_reads_nothing_twice_and_changes_nothing(pipeline, corpus):
    case_id = open_with(pipeline, medical_necessity_letter(corpus))
    first = pipeline.process(case_id, today=TODAY)
    writes = len(pipeline.store.read_audit(case_id))

    second = pipeline.process(case_id, today=TODAY)
    assert len(pipeline.store.read_audit(case_id)) == writes
    assert len(second.case.history) == len(first.case.history)
    assert [e.escalation_id for e in second.escalations] == [
        e.escalation_id for e in first.escalations
    ]


def test_a_supporting_document_is_never_mined_for_denial_facts(pipeline, corpus):
    case_id = open_with(pipeline, medical_necessity_letter(corpus))
    pipeline.ingest(
        case_id,
        filename="lmn.txt",
        kind="letter_of_medical_necessity",
        raw_pages=["I am the treating physician."],
    )
    pending = pipeline.pending_documents(pipeline.store.load(case_id))
    assert [d.kind for d in pending] == ["denial_letter"]


# --- a person acts ----------------------------------------------------------------------------


def test_confirming_a_critical_fact_through_its_escalation(pipeline, corpus):
    case_id = open_with(pipeline, medical_necessity_letter(corpus))
    snapshot = pipeline.process(case_id, today=TODAY)
    ask = next(e for e in verify_escalations(snapshot) if e.subject == "denial.notice_date")

    after = pipeline.answer(case_id, ask.escalation_id, "Confirm", by=ADVOCATE, today=TODAY)

    fact = after.case.fact("denial.notice_date")
    assert fact.status is FactStatus.HUMAN_VERIFIED
    assert fact.verified_by == ADVOCATE
    assert ask.escalation_id not in {e.escalation_id for e in after.escalations}


def test_a_person_resolves_an_ambiguous_letter(pipeline, corpus):
    sample = next(s for s in corpus if s.expected_ambiguous)
    case_id = open_with(pipeline, sample)
    snapshot = pipeline.process(case_id, today=TODAY)
    ask = next(e for e in snapshot.escalations if e.subject == "classification")
    assert snapshot.pack is None

    after = pipeline.answer(
        case_id, ask.escalation_id, "Not Medically Necessary", by=ADVOCATE, today=TODAY
    )
    assert after.pack.id == "medical_necessity"
    assert "classification" not in {e.subject for e in after.escalations}


def test_an_answered_question_needs_an_open_escalation(pipeline, corpus):
    case_id = open_with(pipeline, medical_necessity_letter(corpus))
    pipeline.process(case_id, today=TODAY)
    with pytest.raises(KeyError):
        pipeline.answer(case_id, "esc_does_not_exist", "Yes", by=ADVOCATE, today=TODAY)


def test_the_packet_is_ready_only_once_a_person_has_done_their_part(pipeline, corpus):
    case_id = open_with(pipeline, medical_necessity_letter(corpus))
    snapshot = pipeline.process(case_id, today=TODAY)
    assert snapshot.case.state is not CaseState.PACKET_READY

    for ask in verify_escalations(snapshot):
        snapshot = pipeline.answer(case_id, ask.escalation_id, "Confirm", by=ADVOCATE, today=TODAY)
    pipeline.attach_evidence(case_id, "letter_of_medical_necessity", by=ADVOCATE, today=TODAY)
    pipeline.attach_evidence(case_id, "clinical_notes", by=ADVOCATE, today=TODAY)
    snapshot = pipeline.state_fact(
        case_id, "provider.is_treating_physician", True, by=ADVOCATE, today=TODAY
    )

    assert snapshot.case.state is CaseState.PACKET_READY
    assert snapshot.plan.step("necessity_argument") is not None
    assert snapshot.gate.blocking == ()


# --- filing is a person's act ---------------------------------------------------------------


def test_filing_is_recorded_by_a_person_and_starts_the_plans_clock(pipeline, corpus):
    case_id = open_with(pipeline, medical_necessity_letter(corpus))
    pipeline.process(case_id, today=TODAY)

    snapshot = pipeline.mark_filed(case_id, date(2026, 9, 12), by=ADVOCATE, today=TODAY)

    assert snapshot.case.state is CaseState.SUBMITTED
    assert snapshot.case.history[-1].by == ADVOCATE
    assert snapshot.deadlines.get("deadline.plan_response_due") is not None


def test_the_pipeline_never_moves_a_case_out_of_a_person_only_state(pipeline, corpus):
    case_id = open_with(pipeline, medical_necessity_letter(corpus))
    pipeline.process(case_id, today=TODAY)
    pipeline.mark_filed(case_id, date(2026, 9, 12), by=ADVOCATE, today=TODAY)

    for _ in range(3):
        assert pipeline.process(case_id, today=TODAY).case.state is CaseState.SUBMITTED


def test_a_person_cannot_state_a_deadline(pipeline, corpus):
    case_id = open_with(pipeline, medical_necessity_letter(corpus))
    with pytest.raises(StatusInvariantViolation):
        pipeline.state_fact(
            case_id, "deadline.internal_appeal_due", "2027-01-01", by=ADVOCATE, today=TODAY
        )


# --- a planted instruction ----------------------------------------------------------------------


def test_a_planted_instruction_is_reported_not_obeyed(pipeline, corpus):
    sample = next(s for s in corpus if "injection:system_turn" in s.tags)
    case_id = open_with(pipeline, sample)
    snapshot = pipeline.process(case_id, today=TODAY)

    assert snapshot.gate.by_trigger(Trigger.DOCUMENT_ANOMALY)
    assert snapshot.case.state not in (CaseState.SUBMITTED, CaseState.CLOSED_DEADLINE_MISSED)
