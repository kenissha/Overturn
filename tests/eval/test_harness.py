"""The harness, calibrated.

Before any model is scored, the ruler is checked. An oracle must score perfectly, an
extractor that abstains on everything must never be wrong, and an extractor that
fabricates citations must be stopped at the ledger — otherwise the published numbers mean
nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from overturn.engine.packs import PackRegistry
from overturn.eval.corpus import build_corpus
from overturn.eval.harness import (
    OracleExtractor,
    Outcome,
    null_extractor,
    run_eval,
    score_field,
    values_match,
)
from overturn.ledger.schema import Fact, FactStatus, Provenance

PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"
SOURCE = Provenance(doc_id="d", page=1, char_span=(0, 5), quote="x")


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


@pytest.fixture(scope="module")
def registry():
    return PackRegistry.from_directory(PACKS_DIR)


# --- calibration --------------------------------------------------------------------


def test_the_oracle_scores_perfectly(corpus, registry):
    """If this fails, the harness or the answer key is wrong — not the extractor."""
    report = run_eval(corpus, OracleExtractor(corpus), registry, name="oracle")
    assert report.field_accuracy == 1.0
    assert report.hallucination_rate == 0.0
    assert report.correct_abstention == 1.0
    assert report.classification_accuracy == 1.0
    assert report.deadline_accuracy == 1.0
    assert report.refusals == 0


def test_abstaining_on_everything_is_never_wrong_and_never_useful(corpus, registry):
    report = run_eval(corpus, null_extractor, registry, name="null")
    assert report.field_accuracy == 0.0
    assert report.hallucination_rate is None  # asserted nothing
    assert report.correct_abstention == 1.0
    assert report.classification_accuracy < 0.5


def test_fabricated_citations_never_reach_the_ledger(corpus, registry):
    """An extractor that invents its quotes gets every write refused."""

    def fabricator(inp, writer):
        for name in ("denial.notice_date", "denial.reason_code"):
            writer.write_fact(
                field=name,
                value="2026-01-01" if name.endswith("date") else "CO-50",
                doc_id=inp.doc_id,
                page=1,
                char_span_start=0,
                char_span_end=10,
                quote="text that is not at this position",
                confidence=0.99,
            )

    sample = corpus[:5]
    report = run_eval(sample, fabricator, registry, name="fabricator")
    assert report.refusals == 10
    assert report.hallucination_rate is None
    assert report.outcome_counts[Outcome.UNATTEMPTED] > 0


def test_a_real_citation_does_not_make_a_wrong_value_right(corpus, registry):
    """Provenance proves the quote is on the page, not that the value was read correctly.
    The harness must still count the misreading."""

    def misreader(inp, writer):
        page = inp.pages[0]
        quote = "Member Services Department"
        start = page.index(quote)
        writer.write_fact(
            field="denial.reason_text",
            value="Member Services Department",
            doc_id=inp.doc_id,
            page=1,
            char_span_start=start,
            char_span_end=start + len(quote),
            quote=quote,
            confidence=0.9,
        )

    report = run_eval(corpus[:4], misreader, registry, name="misreader")
    assert report.refusals == 0
    assert report.outcome_counts[Outcome.WRONG_VALUE] == 4
    assert report.hallucination_rate == 1.0


def test_the_report_renders_every_published_metric(corpus, registry):
    text = run_eval(corpus[:3], null_extractor, registry, name="null").to_markdown()
    for label in (
        "Field accuracy",
        "Hallucination rate",
        "Correct abstention",
        "Classification accuracy",
        "Deadline accuracy",
        "Injection detection recall",
        "false-positive rate",
    ):
        assert label in text


# --- scoring rules -------------------------------------------------------------------------


def fact(value, status=FactStatus.EXTRACTED):
    if status is FactStatus.MISSING:
        return Fact(field="denial.reason_code", status=status, reason="r", recorded_by="t")
    return Fact(
        field="denial.reason_code",
        value=value,
        status=status,
        provenance=SOURCE,
        recorded_by="t",
    )


@pytest.mark.parametrize(
    ("gold", "got", "expected"),
    [
        ("CO-50", fact("CO-50"), Outcome.CORRECT),
        ("CO-50", fact("CO-197"), Outcome.WRONG_VALUE),
        ("CO-50", fact(None, FactStatus.MISSING), Outcome.FALSE_ABSTENTION),
        ("CO-50", None, Outcome.UNATTEMPTED),
        (None, fact("CO-50"), Outcome.UNSUPPORTED_VALUE),
        (None, fact(None, FactStatus.MISSING), Outcome.CORRECT_ABSTENTION),
        (None, None, Outcome.SILENT_ABSENT),
    ],
)
def test_score_field(gold, got, expected):
    assert score_field("denial.reason_code", gold, got) is expected


def test_silence_is_not_counted_as_abstention(corpus, registry):
    """Abstention has to be an action. Writing nothing earns no abstention credit."""
    report = run_eval(corpus[:3], lambda inp, writer: None, registry, name="silent")
    assert report.correct_abstention == 0.0


def test_dates_must_match_exactly():
    assert values_match("denial.notice_date", "2026-08-01", "2026-08-01")
    assert not values_match("denial.notice_date", "2026-08-01", "2026-08-02")


def test_code_lists_compare_as_sets():
    assert values_match("service.cpt_codes", ["72148"], ["72148"])
    assert values_match("service.cpt_codes", ["97110", "97140"], ["97140", "97110"])
    assert not values_match("service.cpt_codes", ["72148"], ["72149"])


def test_text_tolerates_trimming_but_not_substitution():
    gold = "the requested service was determined not medically necessary"
    assert values_match("denial.reason_text", gold, gold.upper() + ".")
    assert values_match(
        "denial.reason_text", gold, "Service was determined not medically necessary"
    )
    assert not values_match("denial.reason_text", gold, "prior authorization was not obtained")


def test_booleans_are_not_strings():
    assert values_match("service.is_pre_service", True, True)
    assert not values_match("service.is_pre_service", True, "true")
