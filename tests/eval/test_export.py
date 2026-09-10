"""The exported corpus: uploadable letters and answer keys that match the generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from overturn.eval.corpus import build_corpus
from overturn.eval.export import PAGE_BREAK, export

SAMPLES = Path(__file__).resolve().parents[2] / "corpus" / "samples"


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


def test_export_writes_a_letter_and_an_answer_key_per_sample(tmp_path, corpus):
    assert export(corpus, tmp_path) == len(corpus)
    first = corpus[0]
    assert (tmp_path / f"{first.sample_id}.txt").read_text(encoding="utf-8").split(
        PAGE_BREAK
    ) == first.pages
    key = json.loads((tmp_path / f"{first.sample_id}.json").read_text(encoding="utf-8"))
    assert key["expected_pack"] == first.expected_pack
    assert set(key["gold"]) == set(first.gold)


@pytest.mark.skipif(not SAMPLES.exists(), reason="corpus/samples has not been generated")
def test_the_committed_samples_match_the_generator(corpus):
    """Regenerate with `python -m overturn.eval.export` if this fails."""
    for sample in corpus:
        text = (SAMPLES / f"{sample.sample_id}.txt").read_text(encoding="utf-8")
        assert text.split(PAGE_BREAK) == sample.pages, sample.sample_id
