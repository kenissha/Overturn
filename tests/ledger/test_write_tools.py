"""What the untrusted zone can and cannot do.

These tests are the security claim in executable form. Every refusal here is a sentence
the README is entitled to say.
"""

from __future__ import annotations

import pytest

from overturn.ledger.documents import DocumentText
from overturn.ledger.schema import Document, FactStatus, TrustZone
from overturn.ledger.store import CaseStore
from overturn.tools.ledger_tools import LedgerWriter

PAGE_1 = (
    "NOTICE OF ADVERSE BENEFIT DETERMINATION\n\n"
    "Date of notice: 2026-08-01\n"
    "Member ID: A-9931882\n\n"
    "Based on our review, the requested service was determined not medically necessary "
    "under section 4.2(b) of your plan documents.\n"
)


@pytest.fixture
def writer(tmp_path):
    store = CaseStore(tmp_path)
    case = store.create()
    case.documents.append(
        Document(
            doc_id="doc_denial_001",
            kind="denial_letter",
            filename="denial_2026-08-01.pdf",
            pages=1,
            ingest_method="text",
            trust_zone=TrustZone.UNTRUSTED,
            sha256="0" * 64,
        )
    )
    store.save(case)
    texts = {"doc_denial_001": DocumentText.from_pages("doc_denial_001", [PAGE_1])}
    return LedgerWriter(store, case, actor="ExtractionAgent@test", texts=texts)


def span_of(writer, needle: str) -> tuple[int, int]:
    found = writer.texts["doc_denial_001"].find(1, needle)
    assert found is not None, f"fixture text does not contain {needle!r}"
    return found


# --- the happy path ----------------------------------------------------------------


def test_a_verified_citation_is_recorded(writer):
    quote = "not medically necessary"
    start, end = span_of(writer, quote)

    result = writer.write_fact(
        field="denial.reason_text",
        value="Service determined not medically necessary",
        doc_id="doc_denial_001",
        page=1,
        char_span_start=start,
        char_span_end=end,
        quote=quote,
        confidence=0.94,
    )

    assert result.ok, result.message
    fact = writer.case.fact("denial.reason_text")
    assert fact is not None
    assert fact.status is FactStatus.EXTRACTED
    assert fact.provenance.quote == quote


def test_a_recorded_fact_survives_a_reload(writer):
    quote = "2026-08-01"
    start, end = span_of(writer, quote)
    writer.write_fact(
        field="denial.notice_date",
        value="2026-08-01",
        doc_id="doc_denial_001",
        page=1,
        char_span_start=start,
        char_span_end=end,
        quote=quote,
        confidence=0.99,
    )

    reloaded = writer.store.load(writer.case.case_id)
    assert reloaded.value("denial.notice_date") == "2026-08-01"
    assert reloaded.fact("denial.notice_date").provenance.page == 1


# --- citations are followed, not taken on trust ------------------------------------


def test_a_quote_that_is_not_at_the_span_is_refused(writer):
    """The core addition: supplying provenance is not the same as having it."""
    start, end = span_of(writer, "not medically necessary")

    result = writer.write_fact(
        field="denial.reason_text",
        value="Service was experimental",
        doc_id="doc_denial_001",
        page=1,
        char_span_start=start,
        char_span_end=end,
        quote="determined to be experimental and investigational",
        confidence=0.91,
    )

    assert not result.ok
    assert result.error_type == "ProvenanceNotVerified"
    assert writer.case.fact("denial.reason_text") is None


def test_a_span_outside_the_page_is_refused(writer):
    result = writer.write_fact(
        field="denial.reason_text",
        value="anything",
        doc_id="doc_denial_001",
        page=1,
        char_span_start=90000,
        char_span_end=90050,
        quote="anything",
        confidence=0.5,
    )
    assert not result.ok
    assert result.error_type == "IndexError"


def test_a_citation_to_a_document_not_on_the_case_is_refused(writer):
    result = writer.write_fact(
        field="denial.reason_text",
        value="anything",
        doc_id="doc_that_does_not_exist",
        page=1,
        char_span_start=0,
        char_span_end=5,
        quote="NOTIC",
        confidence=0.5,
    )
    assert not result.ok
    assert result.error_type == "ProvenanceRequired"


def test_an_empty_quote_is_refused(writer):
    result = writer.write_fact(
        field="denial.reason_text",
        value="anything",
        doc_id="doc_denial_001",
        page=1,
        char_span_start=0,
        char_span_end=6,
        quote="   ",
        confidence=0.5,
    )
    assert not result.ok


# --- the field taxonomy is a privilege boundary ------------------------------------


def test_the_extraction_agent_cannot_write_a_deadline(writer):
    """Deadlines are arithmetic. No model touches them, by construction."""
    start, end = span_of(writer, "2026-08-01")

    result = writer.write_fact(
        field="deadline.internal_appeal_due",
        value="2027-01-28",
        doc_id="doc_denial_001",
        page=1,
        char_span_start=start,
        char_span_end=end,
        quote="2026-08-01",
        confidence=0.99,
    )

    assert not result.ok
    assert result.error_type == "FieldNotWritableBy"
    assert "deterministic engine" in result.message


def test_the_extraction_agent_cannot_answer_a_human_judgment(writer):
    """'Was this urgent?' is asked, never inferred."""
    start, end = span_of(writer, "not medically necessary")

    result = writer.write_fact(
        field="service.was_urgent",
        value=True,
        doc_id="doc_denial_001",
        page=1,
        char_span_start=start,
        char_span_end=end,
        quote="not medically necessary",
        confidence=0.8,
    )

    assert not result.ok
    assert result.error_type == "FieldNotWritableBy"


def test_an_invented_field_is_refused(writer):
    start, end = span_of(writer, "NOTICE")
    result = writer.write_fact(
        field="denial.case_should_be_closed",
        value="true",
        doc_id="doc_denial_001",
        page=1,
        char_span_start=start,
        char_span_end=end,
        quote="NOTICE",
        confidence=1.0,
    )
    assert not result.ok
    assert result.error_type == "UnknownField"


# --- abstention is an action, not silence ------------------------------------------


def test_marking_a_field_missing_records_the_reason(writer):
    result = writer.mark_missing(
        "denial.cited_policy_section", "letter references a section but does not name it"
    )
    assert result.ok

    fact = writer.case.fact("denial.cited_policy_section")
    assert fact.status is FactStatus.MISSING
    assert fact.value is None
    assert "does not name it" in fact.reason


def test_marking_missing_without_a_reason_is_refused(writer):
    assert not writer.mark_missing("denial.reason_code", "").ok


def test_write_fact_cannot_be_used_to_record_absence(writer):
    """A null value must go through mark_missing, so abstention is always explicit."""
    result = writer.write_fact(
        field="denial.reason_code",
        value=None,
        doc_id="doc_denial_001",
        page=1,
        char_span_start=0,
        char_span_end=6,
        quote="NOTICE",
        confidence=0.0,
    )
    assert not result.ok
    assert result.error_type == "ProvenanceRequired"


# --- the audit log ------------------------------------------------------------------


def test_refused_writes_are_recorded_not_swallowed(writer):
    """An agent attempting a write it is not entitled to make is itself signal."""
    writer.write_fact(
        field="deadline.internal_appeal_due",
        value="2027-01-28",
        doc_id="doc_denial_001",
        page=1,
        char_span_start=0,
        char_span_end=6,
        quote="NOTICE",
        confidence=1.0,
    )

    audit = writer.store.read_audit(writer.case.case_id)
    refusals = [e for e in audit if e["outcome"] == "refused"]
    assert len(refusals) == 1
    assert refusals[0]["error_type"] == "FieldNotWritableBy"
    assert refusals[0]["field"] == "deadline.internal_appeal_due"
    assert refusals[0]["actor"] == "ExtractionAgent@test"


def test_pii_never_reaches_the_audit_log(writer):
    quote = "A-9931882"
    start, end = span_of(writer, quote)

    writer.write_fact(
        field="patient.member_id",
        value="A-9931882",
        doc_id="doc_denial_001",
        page=1,
        char_span_start=start,
        char_span_end=end,
        quote=quote,
        confidence=0.97,
    )

    assert writer.case.value("patient.member_id") == "A-9931882"

    audit_text = writer.store.audit_path(writer.case.case_id).read_text(encoding="utf-8")
    assert "A-9931882" not in audit_text
    assert "redacted" in audit_text


# --- the agent-facing form: quote, and let the tool find it -------------------------


def test_a_quote_is_located_on_the_page_by_the_tool(writer):
    result = writer.write_fact_by_quote(
        "denial.reason_text",
        "not medically necessary",
        "doc_denial_001",
        1,
        "not medically necessary",
        0.9,
    )
    assert result.ok, result.message
    fact = writer.case.fact("denial.reason_text")
    assert fact.provenance.char_span == span_of(writer, "not medically necessary")


def test_line_breaks_and_case_in_a_quote_are_tolerated(writer):
    result = writer.write_fact_by_quote(
        "denial.reason_text",
        "not medically necessary",
        "doc_denial_001",
        1,
        "NOT medically\n   necessary",
        0.9,
    )
    assert result.ok, result.message


def test_a_quote_wrapped_in_quotation_marks_is_found(writer):
    result = writer.write_fact_by_quote(
        "patient.member_id", "A-9931882", "doc_denial_001", 1, '"A-9931882"', 0.9
    )
    assert result.ok, result.message


def test_a_quote_that_is_not_on_the_page_is_refused(writer):
    result = writer.write_fact_by_quote(
        "denial.reason_text",
        "experimental",
        "doc_denial_001",
        1,
        "determined to be experimental",
        0.9,
    )
    assert not result.ok
    assert result.error_type == "ProvenanceNotVerified"


def test_a_quote_on_a_page_that_does_not_exist_is_refused(writer):
    result = writer.write_fact_by_quote(
        "patient.member_id", "A-9931882", "doc_denial_001", 7, "A-9931882", 0.9
    )
    assert not result.ok
    assert result.error_type == "IndexError"


def test_a_printed_date_is_converted_by_code_not_by_the_model(writer):
    result = writer.write_fact_by_quote(
        "denial.notice_date", "08/01/2026", "doc_denial_001", 1, "2026-08-01", 0.95
    )
    assert result.ok, result.message
    assert writer.case.value("denial.notice_date") == "2026-08-01"


def test_an_unreadable_value_is_refused_and_audited(writer):
    result = writer.write_fact_by_quote(
        "service.is_pre_service", "maybe", "doc_denial_001", 1, "requested service", 0.5
    )
    assert not result.ok
    assert result.error_type == "FactTypeMismatch"
    assert writer.store.read_audit(writer.case.case_id)[-1]["outcome"] == "refused"


def test_quoting_does_not_open_a_path_to_engine_fields(writer):
    result = writer.write_fact_by_quote(
        "deadline.internal_appeal_due", "2027-01-28", "doc_denial_001", 1, "2026-08-01", 1.0
    )
    assert not result.ok
    assert result.error_type == "FieldNotWritableBy"
