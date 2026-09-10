"""When documents disagree, and when a document meets a person's answer.

The ledger never lets the later document silently win. A disagreement is recorded as a
conflict with both sources; a person's confirmation is not overwritten by any document;
and one document being silent does not erase what another states.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from overturn.engine.escalation import Trigger
from overturn.engine.packs import PackRegistry
from overturn.ledger.documents import DocumentText
from overturn.ledger.schema import Document, FactStatus
from overturn.ledger.store import CaseStore
from overturn.pipeline import Pipeline
from overturn.tools.ledger_tools import LedgerWriter

LETTER = "Date of notice: August 1, 2026\nThe service is excluded from coverage.\n"
POLICY = "Evidence of Coverage\nCovered: magnetic resonance imaging (MRI).\n"
AMENDMENT = "Amendment 2\nMRI is covered only with a referral.\n"


@pytest.fixture
def writer(tmp_path):
    store = CaseStore(tmp_path)
    case = store.create()
    texts = {}
    for doc_id, text in (("doc_letter", LETTER), ("doc_policy", POLICY), ("doc_amend", AMENDMENT)):
        texts[doc_id] = DocumentText.from_pages(doc_id, [text])
        case.documents.append(
            Document(doc_id=doc_id, kind="x", filename=f"{doc_id}.txt", pages=1, sha256="0")
        )
    store.save(case)
    return LedgerWriter(store, case, actor="ExtractionAgent@test", texts=texts)


def covers(writer, doc_id, value, quote):
    return writer.write_fact_by_quote("plan.covers_service", value, doc_id, 1, quote, 0.9)


def test_two_documents_that_disagree_are_recorded_as_a_conflict(writer):
    covers(writer, "doc_letter", "false", "excluded from coverage")
    result = covers(writer, "doc_policy", "true", "Covered: magnetic resonance imaging (MRI)")

    fact = writer.case.fact("plan.covers_service")
    assert result.ok and "conflicted" in result.message
    assert fact.status is FactStatus.CONFLICTED
    assert fact.value is None
    assert [(s.reads, s.provenance.doc_id) for s in fact.conflict] == [
        (False, "doc_letter"),
        (True, "doc_policy"),
    ]


def test_a_third_source_joins_the_conflict(writer):
    covers(writer, "doc_letter", "false", "excluded from coverage")
    covers(writer, "doc_policy", "true", "Covered: magnetic resonance imaging (MRI)")
    covers(writer, "doc_amend", "true", "MRI is covered only with a referral")
    assert len(writer.case.fact("plan.covers_service").conflict) == 3


def test_documents_that_agree_do_not_conflict(writer):
    writer.write_fact_by_quote(
        "denial.notice_date", "2026-08-01", "doc_letter", 1, "August 1, 2026", 1
    )
    writer.texts["doc_policy"] = DocumentText.from_pages(
        "doc_policy", ["Notice dated August 1, 2026."]
    )
    writer.write_fact_by_quote(
        "denial.notice_date", "2026-08-01", "doc_policy", 1, "August 1, 2026", 1
    )
    assert writer.case.fact("denial.notice_date").status is FactStatus.EXTRACTED


def test_re_reading_the_same_document_replaces_its_own_reading(writer):
    covers(writer, "doc_letter", "false", "excluded from coverage")
    covers(writer, "doc_letter", "true", "The service is excluded")
    assert writer.case.fact("plan.covers_service").value is True


def test_a_document_does_not_overwrite_what_a_person_stated(writer):
    from overturn.ledger.schema import Fact

    writer.case.facts["plan.covers_service"] = Fact(
        field="plan.covers_service",
        value=True,
        status=FactStatus.HUMAN_ANSWERED,
        verified_by="user_004",
        recorded_by="user_004",
    )
    result = covers(writer, "doc_letter", "false", "excluded from coverage")
    assert result.error_type == "SettledByPerson"
    assert writer.case.fact("plan.covers_service").status is FactStatus.HUMAN_ANSWERED


def test_one_document_being_silent_does_not_erase_another(writer):
    covers(writer, "doc_letter", "false", "excluded from coverage")
    result = writer.mark_missing("plan.covers_service", "the policy excerpt does not say")
    assert result.ok
    assert writer.case.fact("plan.covers_service").value is False


# --- through the pipeline ---------------------------------------------------------------


def test_a_plan_document_that_contradicts_the_denial_reaches_the_advocate(tmp_path):
    from overturn.demo import CONFLICT_DENIAL, CONFLICT_POLICY, AnswerKeyExtractor

    pipeline = Pipeline(
        CaseStore(tmp_path),
        PackRegistry.from_directory(Path(__file__).resolve().parents[2] / "packs"),
        AnswerKeyExtractor([]),
    )
    case_id = pipeline.store.create().case_id
    pipeline.ingest(
        case_id, filename="denial.txt", kind="denial_letter", raw_pages=[CONFLICT_DENIAL]
    )
    pipeline.ingest(case_id, filename="eoc.txt", kind="plan_document", raw_pages=[CONFLICT_POLICY])
    snapshot = pipeline.process(case_id, today=date(2026, 9, 10))

    assert snapshot.case.fact("plan.covers_service").status is FactStatus.CONFLICTED
    asked = [
        e for e in snapshot.gate.by_trigger(Trigger.HUMAN_JUDGMENT) if "disagree" in e.question
    ]
    assert asked and not asked[0].blocking
    assert snapshot.plan.step("policy_conflict") is not None  # the contradiction is argued
