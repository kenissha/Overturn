"""The red-team vector corpus: every vector contained, and detection exactly as published.

Detection expectations are observations, not targets. If the detector improves or
regresses, the vector file and the README change with it — the numbers are never allowed
to drift away from what the code does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from overturn.engine.packs import PackRegistry
from overturn.eval.redteam import (
    CATEGORIES,
    check_containment,
    is_detected,
    load_vectors,
    run,
)

ROOT = Path(__file__).resolve().parents[2]
VECTORS = load_vectors()


@pytest.fixture(scope="module")
def registry():
    return PackRegistry.from_directory(ROOT / "packs")


def test_the_corpus_covers_every_category_with_at_least_fifty_vectors():
    assert len(VECTORS) >= 50
    assert {v.category for v in VECTORS} == set(CATEGORIES)
    assert len({v.id for v in VECTORS}) == len(VECTORS)


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v.id)
def test_detection_is_exactly_as_published(vector):
    assert is_detected(vector) is vector.detected, (
        "detection changed: update tests/redteam/vectors.yaml and the README totals"
    )


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v.id)
def test_every_vector_is_contained(vector, registry, tmp_path):
    result = check_containment(vector, registry, tmp_path)
    assert result.contained, result.problems


def test_the_readme_quotes_the_measured_totals(registry):
    report = run(VECTORS, registry)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"{report.detected} of {report.total}" in readme
    assert f"{report.contained} of {report.total}" in readme
