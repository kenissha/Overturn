"""Rule packs: denial categories as versioned data rather than branches.

A denial category is a declaration of four things: how to recognise it, which facts an
appeal against it needs, which evidence must be on file, and the argument the drafter is
allowed to make. All four live in a YAML file. Adding a sixth category is a file, not a
release.

**Packs contain no executable code.** An earlier design expressed conditional argument
steps as Python expressions to be evaluated at runtime. That would have put an eval() at
the end of a pipeline whose entire premise is that untrusted content cannot reach
privileged execution, so conditions are declarative instead: a condition names a fact and
the status or value it must have, and is checked by the code in this module.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from overturn.engine.deadlines import Regime
from overturn.ledger.fields import EVIDENCE_PREFIX, get_field
from overturn.ledger.schema import Case, FactStatus, FactValue


class MatchRule(BaseModel):
    """One way of recognising a denial category.

    Rules are matched against facts already extracted into the ledger, never against raw
    document text: classification is a deterministic function of grounded facts.
    """

    model_config = ConfigDict(frozen=True)

    reason_code_in: tuple[str, ...] = ()
    phrase_matches: tuple[str, ...] = ()
    phrase_field: str = "denial.reason_text"

    @field_validator("reason_code_in", "phrase_matches")
    @classmethod
    def _not_empty_strings(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in v):
            raise ValueError("match entries cannot be blank")
        return v

    @model_validator(mode="after")
    def _rule_can_match_something(self) -> MatchRule:
        if not self.reason_code_in and not self.phrase_matches:
            raise ValueError(
                "a match rule must name at least one reason code or phrase; an empty rule "
                "matches nothing and silently weakens the pack"
            )
        return self


class PackMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    any_of: tuple[MatchRule, ...] = Field(
        min_length=1,
        description="A pack with no match rules can never be selected, so an empty list "
        "is a dead file rather than a permissive one.",
    )
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    """Facts extracted below this confidence do not count toward a match."""


class EvidenceItem(BaseModel):
    """A document the appeal needs."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    source: str = Field(description="treating_physician, provider_records, public_reference, ...")
    human_only: bool = False
    """Only a person can obtain it. Raises escalation trigger 1 when absent."""
    blocking: bool = True
    """Whether the packet is incomplete without it."""

    @property
    def fact_field(self) -> str:
        return f"{EVIDENCE_PREFIX}{self.id}"


class Condition(BaseModel):
    """A declarative test against one fact. No expressions, no evaluation."""

    model_config = ConfigDict(frozen=True)

    fact: str
    status_is: FactStatus | None = None
    value_is: FactValue = None

    def holds_for(self, case: Case) -> bool:
        fact = case.fact(self.fact)
        if fact is None:
            return False
        if self.status_is is not None and fact.status is not self.status_is:
            return False
        if self.value_is is not None and fact.value != self.value_is:
            return False
        return True


class ArgumentStep(BaseModel):
    """One paragraph the drafter may write, and what it is not allowed to say without."""

    model_config = ConfigDict(frozen=True)

    id: str
    claim: str
    requires_facts: tuple[str, ...] = ()
    requires_evidence: tuple[str, ...] = ()
    condition: Condition | None = None
    """When set, the step is only included if the condition holds."""


class RulePack(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    version: str
    display_name: str
    match: PackMatch
    required_facts: tuple[str, ...] = ()
    required_evidence: tuple[EvidenceItem, ...] = ()
    deadline_regime: str = Field(
        default="aca_internal",
        description="aca_internal lets the engine split pre/post service itself.",
    )
    argument_skeleton: tuple[ArgumentStep, ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"{self.id}@{self.version}"

    def evidence(self, evidence_id: str) -> EvidenceItem | None:
        return next((e for e in self.required_evidence if e.id == evidence_id), None)

    # -- validation ---------------------------------------------------------------

    @field_validator("required_facts")
    @classmethod
    def _facts_exist(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        unknown = [f for f in v if get_field(f) is None]
        if unknown:
            raise ValueError(
                f"required_facts names fields that are not in the taxonomy: {unknown}. "
                "A pack cannot require a fact the ledger has no way to hold."
            )
        return v


class PackValidationError(Exception):
    """A pack on disk is not usable. Raised at load time, never at request time."""


def load_pack(path: str | Path) -> RulePack:
    """Load and validate a single pack file."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PackValidationError(f"{path.name}: not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise PackValidationError(f"{path.name}: expected a mapping at the top level")

    try:
        pack = RulePack.model_validate(raw)
    except Exception as exc:
        raise PackValidationError(f"{path.name}: {exc}") from exc

    _check_internal_references(pack, path.name)
    return pack


def _check_internal_references(pack: RulePack, filename: str) -> None:
    """Catch a pack that refers to its own pieces incorrectly.

    These are the mistakes that would otherwise surface as a silently missing paragraph in
    a drafted appeal, which is the worst place to find them.
    """
    evidence_ids = {item.id for item in pack.required_evidence}

    for step in pack.argument_skeleton:
        unknown_evidence = set(step.requires_evidence) - evidence_ids
        if unknown_evidence:
            raise PackValidationError(
                f"{filename}: argument step {step.id!r} requires evidence "
                f"{sorted(unknown_evidence)} that the pack does not declare."
            )
        unknown_facts = [f for f in step.requires_facts if get_field(f) is None]
        if unknown_facts:
            raise PackValidationError(
                f"{filename}: argument step {step.id!r} requires fields "
                f"{unknown_facts} that are not in the taxonomy."
            )
        if step.condition is not None and get_field(step.condition.fact) is None:
            raise PackValidationError(
                f"{filename}: argument step {step.id!r} has a condition on "
                f"{step.condition.fact!r}, which is not in the taxonomy."
            )

    if pack.deadline_regime not in _ALLOWED_REGIMES:
        raise PackValidationError(
            f"{filename}: deadline_regime {pack.deadline_regime!r} is not recognised. "
            f"Expected one of {sorted(_ALLOWED_REGIMES)}."
        )


_ALLOWED_REGIMES = {"aca_internal"} | {r.value for r in Regime}


class PackRegistry:
    """Every pack available to the engine, loaded once at startup."""

    def __init__(self, packs: list[RulePack]) -> None:
        by_id: dict[str, RulePack] = {}
        for pack in packs:
            if pack.id in by_id:
                raise PackValidationError(
                    f"Two packs share the id {pack.id!r}. Ids must be unique; use the "
                    "version field for revisions."
                )
            by_id[pack.id] = pack
        self._by_id = by_id

    @classmethod
    def from_directory(cls, directory: str | Path) -> PackRegistry:
        directory = Path(directory)
        if not directory.is_dir():
            raise PackValidationError(f"No pack directory at {directory}")
        paths = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
        return cls([load_pack(p) for p in paths])

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self):
        return iter(self._by_id.values())

    def get(self, pack_id: str) -> RulePack | None:
        return self._by_id.get(pack_id)

    def resolve(self, qualified_name: str) -> RulePack | None:
        """Resolve ``id@version``, or a bare id."""
        pack_id = qualified_name.split("@", 1)[0]
        return self._by_id.get(pack_id)

    @property
    def ids(self) -> list[str]:
        return sorted(self._by_id)
