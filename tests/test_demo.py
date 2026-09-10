"""The demo seed: useful for showing the interface, and honest about what it is."""

from __future__ import annotations

from datetime import date

from overturn.demo import ANSWER_KEY_ACTOR, seed
from overturn.ledger.store import CaseStore

TODAY = date(2026, 9, 10)


def test_the_seed_opens_every_corpus_letter_and_leaves_some_for_a_person(tmp_path):
    states = seed(tmp_path, today=TODAY)
    assert sum(states.values()) == 61
    assert states["PACKET_READY"] + states["SUBMITTED"] > 0
    assert states["INTAKE"] > 0  # ambiguous and out-of-scope letters stay for a person


def test_seeded_facts_are_labelled_as_not_coming_from_a_model(tmp_path):
    seed(tmp_path, today=TODAY)
    store = CaseStore(tmp_path)
    actors = {e["actor"] for cid in store.list_case_ids() for e in store.read_audit(cid)}
    assert actors == {ANSWER_KEY_ACTOR}
    assert "not a model" in ANSWER_KEY_ACTOR
