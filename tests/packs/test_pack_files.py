"""The packs that ship, and the guarantees that make a YAML file safe to add.

The claim is that a sixth denial category is a file rather than a release. That claim is
only honest if a malformed file fails loudly at load time instead of producing a quietly
wrong appeal weeks later, so most of this module is about rejection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from overturn.engine.packs import PackRegistry, PackValidationError, load_pack

PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"


@pytest.fixture(scope="module")
def registry() -> PackRegistry:
    return PackRegistry.from_directory(PACKS_DIR)


# --- the shipped packs -----------------------------------------------------------------


def test_every_shipped_pack_loads(registry):
    assert len(registry) >= 2


@pytest.mark.parametrize("path", sorted(PACKS_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_pack_is_valid(path):
    pack = load_pack(path)
    assert pack.id == path.stem, "a pack's id should match its filename"
    assert pack.display_name
    assert pack.match.any_of, "a pack that cannot be matched can never be selected"


@pytest.mark.parametrize("path", sorted(PACKS_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_every_pack_can_produce_an_opening_paragraph(path):
    """A pack with no writable argument would classify a case and then say nothing."""
    pack = load_pack(path)
    assert pack.argument_skeleton
    assert any(step.id == "opening" for step in pack.argument_skeleton)


@pytest.mark.parametrize("path", sorted(PACKS_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_every_pack_requires_at_least_one_blocking_document(path):
    """A category needing no evidence at all is almost certainly an incomplete pack."""
    pack = load_pack(path)
    assert any(item.blocking for item in pack.required_evidence)


@pytest.mark.parametrize("path", sorted(PACKS_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_evidence_ids_are_unique_within_a_pack(path):
    pack = load_pack(path)
    ids = [item.id for item in pack.required_evidence]
    assert len(ids) == len(set(ids))


def test_the_two_shipped_packs_do_not_share_reason_codes(registry):
    """Overlapping codes would make every matching case ambiguous by construction."""
    seen: dict[str, str] = {}
    for pack in registry:
        for rule in pack.match.any_of:
            for code in rule.reason_code_in:
                assert code not in seen, (
                    f"{code} is claimed by both {seen.get(code)} and {pack.id}"
                )
                seen[code] = pack.id


# --- a broken pack fails at load time, not at request time ------------------------------


def write_pack(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "broken.yaml"
    path.write_text(body, encoding="utf-8")
    return path


BASE = """
id: broken
version: 1.0.0
display_name: "Broken"
match:
  any_of:
    - phrase_matches: ["something"]
required_evidence:
  - id: some_document
    label: "Some document"
    source: provider_records
argument_skeleton:
  - id: opening
    claim: "Opening."
"""


def test_a_pack_requiring_a_field_outside_the_taxonomy_is_rejected(tmp_path):
    path = write_pack(tmp_path, BASE + "required_facts:\n  - denial.invented_field\n")
    with pytest.raises(PackValidationError, match="not in the taxonomy"):
        load_pack(path)


def test_an_argument_step_citing_undeclared_evidence_is_rejected(tmp_path):
    """Otherwise this surfaces as a silently missing paragraph in a drafted appeal."""
    body = BASE.replace(
        '  - id: opening\n    claim: "Opening."\n',
        '  - id: opening\n    claim: "Opening."\n'
        "    requires_evidence:\n      - a_document_never_declared\n",
    )
    with pytest.raises(PackValidationError, match="does not declare"):
        load_pack(write_pack(tmp_path, body))


def test_a_condition_on_an_unknown_field_is_rejected(tmp_path):
    body = BASE.replace(
        '  - id: opening\n    claim: "Opening."\n',
        '  - id: opening\n    claim: "Opening."\n'
        "    condition:\n      fact: plan.made_up\n      value_is: true\n",
    )
    with pytest.raises(PackValidationError, match="not in the taxonomy"):
        load_pack(write_pack(tmp_path, body))


def test_an_unrecognised_deadline_regime_is_rejected(tmp_path):
    path = write_pack(tmp_path, BASE + "deadline_regime: made_up_regime\n")
    with pytest.raises(PackValidationError, match="not recognised"):
        load_pack(path)


def test_invalid_yaml_is_rejected_with_the_filename(tmp_path):
    path = write_pack(tmp_path, "id: broken\n  bad indentation: [")
    with pytest.raises(PackValidationError, match="broken.yaml"):
        load_pack(path)


def test_two_packs_sharing_an_id_are_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text(BASE, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(BASE, encoding="utf-8")
    with pytest.raises(PackValidationError, match="share the id"):
        PackRegistry.from_directory(tmp_path)


def test_a_pack_with_no_match_rules_is_rejected(tmp_path):
    body = """
id: unmatched
version: 1.0.0
display_name: "Unmatched"
match:
  any_of: []
"""
    with pytest.raises(PackValidationError):
        load_pack(write_pack(tmp_path, body))
