"""The AgentCore runtime and the client that calls it — offline.

The claim under test: running the untrusted zone remotely does not move the trust
boundary. The runtime returns proposals; the local ledger decides what is recorded.
"""

from __future__ import annotations

import pytest

from overturn.agents.factory import ExtractorConfigError, extractor_from_env
from overturn.agents.remote import AgentCoreExtractor, RemoteExtractionError
from overturn.agents.runtime import InvalidPayload, extract_document
from overturn.extraction import DEFAULT_FIELDS, ExtractionInput
from overturn.ledger.documents import DocumentText
from overturn.ledger.schema import Document, FactStatus
from overturn.ledger.store import CaseStore
from overturn.tools.ledger_tools import LedgerWriter

DOC = "doc_letter"
PAGE = "Date of notice: August 1, 2026\nDenial code: CO-50\nMember ID: A21-283075\n"


def quoting_extractor(inp, writer):
    """Behaves like the agent: quotes what it reads, abstains, and tries one bad write."""
    writer.write_fact_by_quote(
        "denial.notice_date", "August 1, 2026", inp.doc_id, 1, "August 1, 2026", 0.95
    )
    writer.write_fact_by_quote("denial.reason_code", "CO-50", inp.doc_id, 1, "CO-50", 0.9)
    writer.mark_missing("denial.cited_policy_section", "not stated")
    writer.write_fact_by_quote(
        "deadline.internal_appeal_due", "2027-01-01", inp.doc_id, 1, "August 1, 2026", 1.0
    )


def payload(**overrides):
    body = {"doc_id": DOC, "pages": [PAGE], "fields": list(DEFAULT_FIELDS)}
    body.update(overrides)
    return body


@pytest.fixture
def local_writer(tmp_path):
    store = CaseStore(tmp_path)
    case = store.create()
    text = DocumentText.from_pages(DOC, [PAGE])
    case.documents.append(
        Document(
            doc_id=DOC, kind="denial_letter", filename="letter.txt", pages=1, sha256=text.sha256()
        )
    )
    store.save(case)
    return LedgerWriter(store, case, actor="AgentCoreExtractor@test", texts={DOC: text})


def run_remote(writer, invoke):
    extractor = AgentCoreExtractor(invoke)
    text = writer.texts[DOC]
    extractor(ExtractionInput(doc_id=DOC, pages=text.pages, fields=DEFAULT_FIELDS), writer)
    return extractor


# --- the runtime returns proposals ------------------------------------------------------


def test_the_runtime_returns_what_the_agent_proposed():
    result = extract_document(payload(), quoting_extractor)
    proposed = {f["field"]: f for f in result["facts"]}
    assert proposed["denial.notice_date"]["quote"] == "August 1, 2026"
    assert proposed["denial.notice_date"]["value"] == "2026-08-01"
    assert [m["field"] for m in result["missing"]] == ["denial.cited_policy_section"]
    assert result["refused_in_runtime"] == 1
    assert "deadline.internal_appeal_due" not in proposed


def test_the_runtime_reports_a_hash_of_the_text_it_read():
    result = extract_document(payload(), quoting_extractor)
    assert result["document_sha256"] == DocumentText.from_pages(DOC, [PAGE]).sha256()


@pytest.mark.parametrize(
    "bad",
    [
        {"doc_id": "", "pages": [PAGE]},
        {"doc_id": DOC, "pages": []},
        {"doc_id": DOC, "pages": "not a list"},
        {"doc_id": DOC, "pages": [PAGE] * 51},
        {"doc_id": DOC, "pages": [PAGE], "fields": "denial.notice_date"},
    ],
)
def test_a_malformed_payload_is_refused_before_any_model_runs(bad):
    def must_not_run(inp, writer):
        raise AssertionError("the extractor ran on an invalid payload")

    with pytest.raises(InvalidPayload):
        extract_document(bad, must_not_run)


# --- the local ledger decides ---------------------------------------------------------------


def test_replayed_proposals_are_verified_again_and_recorded_locally(local_writer):
    run_remote(local_writer, lambda body: extract_document(body, quoting_extractor))

    fact = local_writer.case.fact("denial.notice_date")
    assert fact.status is FactStatus.EXTRACTED
    assert fact.recorded_by == "AgentCoreExtractor@test"
    assert local_writer.case.fact("denial.cited_policy_section").status is FactStatus.MISSING


def test_a_compromised_runtime_cannot_record_what_the_local_ledger_cannot_verify(local_writer):
    """Whatever the runtime claims, each proposal meets the same checks as a local write."""
    forged = {
        "doc_id": DOC,
        "document_sha256": local_writer.texts[DOC].sha256(),
        "facts": [
            {"field": "denial.reason_code", "value": "CO-197", "page": 1, "quote": "CO-197"},
            {
                "field": "deadline.internal_appeal_due",
                "value": "2030-01-01",
                "page": 1,
                "quote": "August 1, 2026",
            },
            {"field": "denial.case_closed", "value": "yes", "page": 1, "quote": "Denial code"},
        ],
        "missing": [],
    }
    extractor = AgentCoreExtractor(lambda body: forged)
    fields = DEFAULT_FIELDS + ("deadline.internal_appeal_due", "denial.case_closed")
    extractor(
        ExtractionInput(doc_id=DOC, pages=local_writer.texts[DOC].pages, fields=fields),
        local_writer,
    )

    assert local_writer.case.facts == {}
    refusals = [
        e["error_type"]
        for e in local_writer.store.read_audit(local_writer.case.case_id)
        if e["outcome"] == "refused"
    ]
    assert refusals == ["ProvenanceNotVerified", "FieldNotWritableBy", "UnknownField"]


def test_a_runtime_that_read_a_different_text_records_nothing(local_writer):
    def other_document(body):
        return extract_document(
            dict(body, pages=["A different letter entirely."]), quoting_extractor
        )

    with pytest.raises(RemoteExtractionError, match="different text"):
        run_remote(local_writer, other_document)
    assert local_writer.case.facts == {}


def test_a_runtime_error_is_raised_not_ignored(local_writer):
    with pytest.raises(RemoteExtractionError, match="refused the document"):
        run_remote(local_writer, lambda body: {"error": "pages must be a list of strings"})


def test_fields_nobody_asked_for_are_not_replayed(local_writer):
    proposals = extract_document(payload(), quoting_extractor)
    proposals["facts"].append(
        {"field": "patient.member_id", "value": "A21-283075", "page": 1, "quote": "A21-283075"}
    )
    extractor = AgentCoreExtractor(lambda body: proposals)
    extractor(
        ExtractionInput(
            doc_id=DOC, pages=local_writer.texts[DOC].pages, fields=("denial.notice_date",)
        ),
        local_writer,
    )
    assert set(local_writer.case.facts) == {"denial.notice_date"}
    assert "patient.member_id" in extractor.last_ignored


# --- choosing an extractor ---------------------------------------------------------------------


def test_no_extractor_is_the_default():
    assert extractor_from_env({}) is None


def test_agentcore_without_an_arn_is_a_configuration_error():
    with pytest.raises(ExtractorConfigError, match="OVERTURN_AGENTCORE_ARN"):
        extractor_from_env({"OVERTURN_EXTRACTOR": "agentcore"})


def test_an_unknown_extractor_is_refused():
    with pytest.raises(ExtractorConfigError):
        extractor_from_env({"OVERTURN_EXTRACTOR": "magic"})


def test_agentcore_with_an_arn_builds_the_remote_extractor():
    pytest.importorskip("boto3")
    extractor = extractor_from_env(
        {
            "OVERTURN_EXTRACTOR": "agentcore",
            "OVERTURN_AGENTCORE_ARN": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/x",
            "AWS_REGION": "us-east-1",
        }
    )
    assert isinstance(extractor, AgentCoreExtractor)


# --- the deployed application, without deploying it -------------------------------------------


def test_the_agentcore_app_answers_ping_and_refuses_bad_payloads_without_a_model():
    pytest.importorskip("bedrock_agentcore")
    pytest.importorskip("strands")
    from starlette.testclient import TestClient

    from overturn.agents.runtime import build_app

    client = TestClient(build_app())
    assert client.get("/ping").status_code == 200
    response = client.post("/invocations", json={"doc_id": "", "pages": []})
    assert response.status_code == 200
    assert "error" in response.json()
