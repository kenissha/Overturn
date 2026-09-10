"""The corpus: deterministic, correctly labelled, and honest about what it contains.

A wrong answer key is worse than none: it penalises a correct extractor and rewards a
wrong one. These tests hold the key to the text it describes.
"""

from __future__ import annotations

from collections import Counter

import pytest

from overturn.engine.anomalies import scan_document
from overturn.eval.corpus import EXTRACTION_FIELDS, STYLES, build_corpus
from overturn.ledger.documents import normalise


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


# --- determinism ---------------------------------------------------------------------


def test_the_same_seed_produces_the_same_corpus():
    assert [s.model_dump() for s in build_corpus(7)] == [s.model_dump() for s in build_corpus(7)]


def test_a_different_seed_changes_details_but_not_composition():
    a, b = build_corpus(1), build_corpus(2)
    assert [s.pages for s in a] != [s.pages for s in b]
    assert Counter(tuple(s.tags) for s in a).keys() == Counter(tuple(s.tags) for s in b).keys()
    assert len(a) == len(b)


# --- composition -----------------------------------------------------------------------


def test_composition(corpus):
    assert len(corpus) == 60
    assert sum(s.expected_ambiguous for s in corpus) == 6
    assert sum("out_of_scope" in s.tags for s in corpus) == 4
    assert sum(bool(s.expected_anomalies) for s in corpus) == 8
    assert sum("fact_poisoning" in s.tags for s in corpus) == 4
    assert sum("no_notice_date" in s.tags for s in corpus) == 2


def test_every_house_style_is_represented(corpus):
    assert {s.style for s in corpus} == set(STYLES)


def test_both_packs_are_represented_in_balance(corpus):
    counts = Counter(s.expected_pack for s in corpus if s.expected_pack)
    assert abs(counts["medical_necessity"] - counts["prior_authorization"]) <= 4


def test_style_basis_is_labelled_honestly(corpus):
    """Only the model-notice style claims a basis beyond 'synthetic'."""
    for s in corpus:
        expected = "federal_model_notice_structure" if s.style == "model_notice" else "synthetic"
        assert s.style_basis == expected


# --- the answer key describes the text ---------------------------------------------------


def test_every_sample_has_a_gold_entry_for_every_scored_field(corpus):
    for s in corpus:
        assert set(s.gold) == set(EXTRACTION_FIELDS), s.sample_id


def test_every_gold_quote_appears_on_its_page(corpus):
    for s in corpus:
        for gold in s.gold.values():
            if gold.value is None:
                assert gold.quote is None
                continue
            assert gold.quote in normalise(s.pages[gold.page - 1]), (s.sample_id, gold.field)


def test_a_letter_with_no_date_has_no_gold_date(corpus):
    for s in (s for s in corpus if "no_notice_date" in s.tags):
        assert s.gold["denial.notice_date"].value is None


def test_the_statutory_window_is_not_mistaken_for_a_stated_deadline(corpus):
    """'Within 180 days' appears in every letter. It is a rule, not a date on the notice,
    and computing it is the engine's job. The key must never treat it as stated."""
    unstated = [s for s in corpus if s.gold["denial.stated_appeal_deadline"].value is None]
    assert unstated
    for s in unstated:
        assert "180 days" in " ".join(s.pages)


def test_missing_optional_fields_actually_occur(corpus):
    """Abstention can only be measured if the corpus contains things to abstain on."""
    absent = Counter(name for s in corpus for name, g in s.gold.items() if g.value is None)
    assert absent["denial.reason_code"] >= 5
    assert absent["denial.cited_policy_section"] >= 5
    assert absent["denial.stated_appeal_deadline"] >= 10


def test_multi_reason_letters_carry_both_reasons(corpus):
    for s in (s for s in corpus if s.expected_ambiguous):
        reason = s.gold["denial.reason_text"].value
        assert "in addition" in reason
        assert s.expected_pack is None


# --- planted content -----------------------------------------------------------------------


def test_clean_letters_raise_no_anomalies(corpus):
    """The detector's false-positive rate on realistic letters, held at zero."""
    for s in (s for s in corpus if s.is_clean):
        assert scan_document(s.doc_id, s.pages) == [], s.sample_id


def test_every_planted_instruction_is_detected(corpus):
    for s in (s for s in corpus if s.expected_anomalies):
        found = {a.kind.value for a in scan_document(s.doc_id, s.pages)}
        assert set(s.expected_anomalies) <= found, (s.sample_id, found)


def test_a_poisoned_letter_contains_a_second_notice_date(corpus):
    for s in (s for s in corpus if "fact_poisoning" in s.tags):
        assert " ".join(s.pages).count("Date of notice") == 2


def test_names_are_fictional(corpus):
    """No real insurer is imitated. Checked against the names we ship, not a blocklist."""
    from overturn.eval.corpus import ISSUERS

    for s in corpus:
        assert s.gold["plan.issuer"].value in ISSUERS


ORIGINAL_48_DIGEST = "6b023dbe00d963cbe2dc2fdd3932d26fffe3f948285625175c55f478ab41976d"
"""SHA-256 of the first 48 letters' text, recorded before the later categories were added."""


def test_every_installed_rule_pack_has_letters(corpus):
    """A pack the corpus never exercises is a pack whose classification is unmeasured."""
    from pathlib import Path

    from overturn.engine.packs import PackRegistry

    registry = PackRegistry.from_directory(Path(__file__).resolve().parents[2] / "packs")
    covered = {s.expected_pack for s in corpus if s.expected_pack}
    assert covered == set(registry.ids)


def test_adding_categories_left_the_original_letters_unchanged(corpus):
    """The first 48 letters are what earlier results and the demo were built on."""
    import hashlib

    digest = hashlib.sha256("".join("".join(s.pages) for s in corpus[:48]).encode()).hexdigest()
    assert digest == ORIGINAL_48_DIGEST
