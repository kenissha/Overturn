"""The HTTP surface, exercised the way the interface uses it.

Extraction is a content-matching oracle that writes the answer key through the
agent-facing tool (quote and page, span located by the tool), so these tests cover the
same write path the model uses.
"""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from overturn.api.app import create_app  # noqa: E402
from overturn.eval.corpus import build_corpus  # noqa: E402
from overturn.ledger.documents import normalise  # noqa: E402

TODAY = date(2026, 9, 10)


class ContentOracle:
    """Recognises a corpus letter by its text and writes its answer key by quoting."""

    def __init__(self, corpus):
        self._by_text = {tuple(normalise(p) for p in s.pages): s for s in corpus}

    def __call__(self, inp, writer):
        sample = self._by_text[tuple(inp.pages)]
        for name in inp.fields:
            gold = sample.gold[name]
            if gold.value is None:
                writer.mark_missing(name, "not stated in the notice")
            else:
                result = writer.write_fact_by_quote(
                    name, gold.value, inp.doc_id, gold.page, gold.quote, 1.0
                )
                assert result.ok, result.message


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


@pytest.fixture
def client(tmp_path, corpus):
    app = create_app(data_dir=tmp_path, extractor=ContentOracle(corpus), today=lambda: TODAY)
    return TestClient(app)


def letter(corpus, **kind):
    if "tag" in kind:
        return next(s for s in corpus if kind["tag"] in s.tags)
    return next(
        s
        for s in corpus
        if s.expected_pack == "medical_necessity"
        and s.is_clean
        and s.gold["denial.cited_policy_section"].value
    )


def open_case(client, sample) -> str:
    case_id = client.post("/api/cases").json()["case_id"]
    response = client.post(
        f"/api/cases/{case_id}/documents/text",
        json={"filename": f"{sample.sample_id}.txt", "pages": sample.pages},
    )
    assert response.status_code == 201
    return case_id


def processed(client, sample) -> tuple[str, dict]:
    case_id = open_case(client, sample)
    return case_id, client.post(f"/api/cases/{case_id}/process").json()["case"]


# --- reading a letter ------------------------------------------------------------------


def test_health_reports_the_installed_packs(client):
    body = client.get("/api/health").json()
    assert body["ok"] and body["extractor"]
    assert "medical_necessity" in body["packs"]


def test_a_processed_letter_arrives_classified_with_its_gaps(client, corpus):
    _, case = processed(client, letter(corpus))
    assert case["pack"]["id"] == "medical_necessity"
    assert case["state"] == "AWAITING_DOCUMENT"
    assert case["escalations"]
    fields = {f["field"]: f for f in case["ledger"]}
    assert fields["denial.notice_date"]["status"] == "extracted"
    assert fields["denial.notice_date"]["critical"] is True


def test_every_citation_highlights_exactly_its_quote(client, corpus):
    """The split view's promise: hover a fact, and the span on the page is its quote."""
    case_id, case = processed(client, letter(corpus))
    doc_id = case["documents"][0]["doc_id"]
    pages = client.get(f"/api/cases/{case_id}/documents/{doc_id}").json()["pages"]

    cited = [f for f in case["ledger"] if f["provenance"]]
    assert cited
    for fact in cited:
        p = fact["provenance"]
        start, end = p["char_span"]
        assert pages[p["page"] - 1][start:end] == p["quote"]


def test_a_field_the_letter_does_not_state_is_shown_as_a_gap_with_a_reason(client, corpus):
    sample = next(s for s in corpus if s.is_clean and s.gold["denial.reason_code"].value is None)
    _, case = processed(client, sample)
    code = next(f for f in case["ledger"] if f["field"] == "denial.reason_code")
    assert code["status"] == "missing"
    assert code["value"] is None
    assert code["reason"]


def test_fields_never_read_are_listed_rather_than_hidden(client, corpus):
    case_id = open_case(client, letter(corpus))
    case = client.get(f"/api/cases/{case_id}").json()
    assert {f["status"] for f in case["ledger"]} == {"not_looked_for"}


# --- a person acts ------------------------------------------------------------------------


def test_confirming_through_an_escalation(client, corpus):
    case_id, case = processed(client, letter(corpus))
    ask = next(e for e in case["escalations"] if e["options"] == ["Confirm", "Correct it"])

    after = client.post(
        f"/api/cases/{case_id}/escalations/{ask['id']}/answer",
        json={"answer": "Confirm"},
        headers={"X-Overturn-User": "user_004"},
    ).json()

    fact = next(f for f in after["ledger"] if f["field"] == ask["subject"])
    assert fact["status"] == "human_verified"
    assert fact["verified_by"] == "user_004"


def test_answering_a_closed_question_is_a_conflict(client, corpus):
    case_id, _ = processed(client, letter(corpus))
    response = client.post(
        f"/api/cases/{case_id}/escalations/esc_nope/answer", json={"answer": "Yes"}
    )
    assert response.status_code == 409


def test_a_person_cannot_state_a_deadline_over_http(client, corpus):
    case_id, _ = processed(client, letter(corpus))
    response = client.put(
        f"/api/cases/{case_id}/facts/deadline.internal_appeal_due", json={"value": "2027-01-01"}
    )
    assert response.status_code == 422


def test_filing_is_a_record_not_a_submission(client, corpus):
    case_id, _ = processed(client, letter(corpus))
    case = client.post(f"/api/cases/{case_id}/filed", json={"filed_on": "2026-09-12"}).json()
    assert case["state"] == "SUBMITTED"
    assert case["history"][-1]["by"] == "advocate"


# --- outputs ----------------------------------------------------------------------------------


def test_there_is_no_letter_before_there_is_a_category(client, corpus):
    case_id = open_case(client, letter(corpus))
    assert client.get(f"/api/cases/{case_id}/letter").status_code == 409


def test_the_draft_says_it_has_not_been_sent(client, corpus):
    case_id, _ = processed(client, letter(corpus))
    body = client.get(f"/api/cases/{case_id}/letter").json()
    assert "has not been sent" in body["text"]


def test_the_audit_trail_is_exposed_without_pii_values(client, corpus):
    sample = letter(corpus)
    case_id, _ = processed(client, sample)
    audit = client.get(f"/api/cases/{case_id}/audit").json()
    assert audit
    assert sample.gold["patient.member_id"].value not in str(audit)


# --- the morning queue ---------------------------------------------------------------------


def test_the_queue_puts_what_needs_a_person_first_and_counts_the_rest(client, corpus):
    for sample in [s for s in corpus if s.is_clean][:5]:
        processed(client, sample)
    queue = client.get("/api/queue").json()
    assert len(queue["attention"]) <= 3
    assert queue["attention_total"] + queue["quiet_count"] >= 5
    for card in queue["attention"]:
        assert card["top"]["why_it_matters"]


# --- planted instructions ---------------------------------------------------------------------


def test_a_planted_instruction_is_shown_on_the_page_it_came_from(client, corpus):
    case_id, case = processed(client, letter(corpus, tag="injection:override"))
    assert any(e["trigger"] == 4 for e in case["escalations"])
    doc_id = case["documents"][0]["doc_id"]
    anomalies = client.get(f"/api/cases/{case_id}/documents/{doc_id}").json()["anomalies"]
    assert any(a["kind"] == "instruction_pattern" and a["char_span"] for a in anomalies)


# --- uploads and edges ----------------------------------------------------------------------


def test_a_text_upload_splits_pages_on_form_feeds(client):
    case_id = client.post("/api/cases").json()["case_id"]
    response = client.post(
        f"/api/cases/{case_id}/documents",
        files={"file": ("letter.txt", b"Page one text.\fPage two text.", "text/plain")},
    )
    assert response.status_code == 201
    assert response.json()["case"]["documents"][0]["pages"] == 2


def test_an_unknown_case_is_not_found(client):
    assert client.get("/api/cases/case_nope").status_code == 404


def test_without_an_extractor_documents_are_stored_but_not_read(tmp_path, corpus):
    client = TestClient(create_app(data_dir=tmp_path, today=lambda: TODAY))
    case_id = open_case(client, letter(corpus))
    body = client.post(f"/api/cases/{case_id}/process").json()
    assert body["extractor"] is False
    assert body["documents_read"] == 0
    assert body["case"]["state"] == "INTAKE"


def test_the_quiet_count_is_every_file_that_needs_no_one(client, corpus):
    for sample in [s for s in corpus if s.is_clean][:4]:
        processed(client, sample)
    queue = client.get("/api/queue").json()
    total = len(client.get("/api/cases").json())
    assert queue["attention_total"] + queue["quiet_count"] == total


def test_a_pinned_clock_is_reported_so_the_interface_can_say_so(tmp_path):
    health = TestClient(create_app(data_dir=tmp_path, today=lambda: TODAY)).get("/api/health")
    assert health.json()["today"] == TODAY.isoformat()
    assert health.json()["fixed_clock"] is True
