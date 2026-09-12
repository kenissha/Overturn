"""A real model calls several tools at once. The ledger settles them one at a time.

Strands runs an agent's tool calls in parallel threads. Before the write paths were
serialised, two calls landing together interleaved inside the audit file and left a line
that could not be parsed — which is how a sixty-letter evaluation run died.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from overturn.ledger.documents import DocumentText
from overturn.ledger.schema import Document, FactStatus
from overturn.ledger.store import CaseStore
from overturn.tools.ledger_tools import LedgerWriter

PAGE = (
    "Date of notice: August 1, 2026\nDenial code: CO-50\n"
    "Service: MRI of the lumbar spine\nProcedure code: 72148\n"
    "Member ID: A12-993\nProvider: Dr. Lena Ortiz\nDate of service: July 3, 2026\n"
)

WRITES = [
    ("denial.notice_date", "2026-08-01", "August 1, 2026"),
    ("denial.reason_code", "CO-50", "CO-50"),
    ("service.description", "MRI of the lumbar spine", "MRI of the lumbar spine"),
    ("service.cpt_codes", "72148", "72148"),
    ("patient.member_id", "A12-993", "A12-993"),
    ("provider.name", "Dr. Lena Ortiz", "Dr. Lena Ortiz"),
    ("service.date_of_service", "2026-07-03", "July 3, 2026"),
]


@pytest.fixture
def writer(tmp_path):
    store = CaseStore(tmp_path)
    case = store.create()
    text = DocumentText.from_pages("doc_x", [PAGE])
    case.documents.append(
        Document(doc_id="doc_x", kind="denial_letter", filename="d.txt", pages=1, sha256="0")
    )
    store.save(case)
    return LedgerWriter(store, case, actor="ExtractionAgent@test", texts={"doc_x": text})


def test_tool_calls_made_at_once_all_land_and_the_audit_stays_readable(writer):
    def run(job):
        field, value, quote = job
        return writer.write_fact_by_quote(field, value, "doc_x", 1, quote, 1.0)

    with ThreadPoolExecutor(max_workers=len(WRITES)) as pool:
        results = list(pool.map(run, WRITES * 3))

    assert all(r.ok for r in results), [r.message for r in results if not r.ok]

    # Every field is recorded, and the audit parses: one line per attempt, none torn.
    for field, _value, _quote in WRITES:
        assert writer.case.fact(field).status is FactStatus.EXTRACTED, field
    audit = writer.store.read_audit(writer.case.case_id)
    assert len(audit) == len(WRITES) * 3
    assert {e["outcome"] for e in audit} == {"accepted"}


def test_a_field_written_and_abstained_on_at_once_ends_in_one_state(writer):
    def write(_):
        return writer.write_fact_by_quote("denial.reason_code", "CO-50", "doc_x", 1, "CO-50", 1.0)

    def absent(_):
        return writer.mark_missing("denial.reason_code", "not stated")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: write(i) if i % 2 else absent(i), range(16)))

    fact = writer.case.fact("denial.reason_code")
    assert fact.status in (FactStatus.EXTRACTED, FactStatus.MISSING)
    assert len(writer.store.read_audit(writer.case.case_id)) == 16
