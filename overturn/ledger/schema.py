"""Ledger schema and its invariants.

The ledger is the single source of truth in Overturn. The rules engine, the drafter and
the interface all read from here and nowhere else, so the guarantees this module enforces
are the guarantees the product makes.

The central one:

    A fact that carries a value must be able to point at the document, page and character
    span it came from.

There is no path around it. A model cannot record a value it cannot source, because
:class:`Fact` will refuse to be constructed. That is the difference between asking a model
not to hallucinate and making it structurally unable to.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from overturn.ledger.errors import (
    FactTypeMismatch,
    ProvenanceRequired,
    StatusInvariantViolation,
    UnknownField,
)
from overturn.ledger.fields import FactKind, FieldSpec, get_field

FactValue = str | bool | int | float | list[str] | None


def utcnow() -> datetime:
    return datetime.now(UTC)


class FactStatus(StrEnum):
    """What is known about a fact, and how much it can be relied on.

    ``MISSING`` is the reason this enum exists. Most systems represent an unknown value as
    an absent key and then quietly fill it with something plausible. Here an unknown value
    is a first-class recorded state, with a reason attached, that the interface renders as
    a visible gap.
    """

    EXTRACTED = "extracted"
    """A model found it and recorded a source. Not yet checked by a person."""

    HUMAN_VERIFIED = "human_verified"
    """A person confirmed it. The only status a critical field may act on."""

    MISSING = "missing"
    """No source was found. Deliberately not invented."""

    CONFLICTED = "conflicted"
    """Two sources disagree. Often an argument for the appeal rather than a problem."""

    REGIME_DEFAULT = "regime_default"
    """Filled from a statutory default because the document stated nothing.

    Kept distinct from ``EXTRACTED`` so the interface can render it differently and never
    imply the letter said something it did not.
    """

    NOT_APPLICABLE = "not_applicable"
    """Not required for this denial category."""

    HUMAN_ANSWERED = "human_answered"
    """A person supplied it, and no document on file states it.

    The answer to an escalation: whether a service was urgent, the date an appeal was
    filed, that a physician's letter is now on file. It carries no document provenance
    because its source is the person, who is named in ``verified_by``. Deadline fields can
    never hold it: those are computed, not stated.
    """


class TrustZone(StrEnum):
    """Whether content may be read by an agent that holds outward-facing tools."""

    UNTRUSTED = "untrusted"
    """Raw document content. Readable only by agents with no outward-facing tools."""

    TRUSTED = "trusted"
    """Ledger-derived content. Safe for agents that can act."""


class CaseState(StrEnum):
    INTAKE = "INTAKE"
    CLASSIFIED = "CLASSIFIED"
    EVIDENCE_GAP = "EVIDENCE_GAP"
    AWAITING_DOCUMENT = "AWAITING_DOCUMENT"
    PACKET_READY = "PACKET_READY"
    SUBMITTED = "SUBMITTED"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    DECISION = "DECISION"
    RESOLVED_OVERTURNED = "RESOLVED_OVERTURNED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    EXTERNAL_REVIEW_ELIGIBLE = "EXTERNAL_REVIEW_ELIGIBLE"
    EXTERNAL_REVIEW = "EXTERNAL_REVIEW"
    CLOSED_DEADLINE_MISSED = "CLOSED_DEADLINE_MISSED"


class Provenance(BaseModel):
    """Where a value came from, precisely enough to highlight it on the page.

    ``char_span`` indexes into the document's normalised text. The interface uses it to
    highlight the source sentence when the reader hovers the fact, which is what makes the
    grounding claim checkable by eye instead of taken on trust.
    """

    model_config = ConfigDict(frozen=True)

    doc_id: str
    page: int = Field(ge=1)
    char_span: tuple[int, int]
    bbox: tuple[float, float, float, float] | None = None
    quote: str | None = Field(
        default=None,
        description="The sourced text, copied at extraction time so the interface can "
        "render it without re-reading the document.",
    )

    @field_validator("char_span")
    @classmethod
    def _span_is_ordered(cls, v: tuple[int, int]) -> tuple[int, int]:
        start, end = v
        if start < 0 or end < 0:
            raise ValueError("char_span offsets must be non-negative")
        if end <= start:
            raise ValueError("char_span end must be greater than start")
        return v


class ConflictSource(BaseModel):
    """One side of a disagreement between two documents."""

    model_config = ConfigDict(frozen=True)

    reads: FactValue
    provenance: Provenance


class Fact(BaseModel):
    """A single field in the ledger, with everything known about its trustworthiness."""

    model_config = ConfigDict(validate_assignment=True)

    field: str
    value: FactValue = None
    status: FactStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    provenance: Provenance | None = None
    conflict: list[ConflictSource] = Field(default_factory=list)

    reason: str | None = Field(
        default=None,
        description="Why the value is absent. Required when status is missing, so a gap "
        "always explains itself.",
    )
    regime: str | None = Field(
        default=None,
        description="The statutory regime a regime_default value came from.",
    )
    escalation_id: str | None = None

    recorded_at: datetime = Field(default_factory=utcnow)
    recorded_by: str = Field(description="Agent version or user id that wrote this fact.")
    verified_by: str | None = None
    verified_at: datetime | None = None

    # -- invariants ---------------------------------------------------------------

    @model_validator(mode="after")
    def _enforce_invariants(self) -> Fact:
        spec = get_field(self.field)
        if spec is None:
            raise UnknownField(
                f"{self.field!r} is not in the fact taxonomy. Unknown field names are "
                "refused: accepting them would let planted text invent a field."
            )
        self._check_status_shape()
        if self.value is not None:
            _check_value_kind(spec, self.value)
        for side in self.conflict:
            if side.reads is not None:
                _check_value_kind(spec, side.reads)
        return self

    def _check_status_shape(self) -> None:
        status = self.status

        if status in (FactStatus.EXTRACTED, FactStatus.HUMAN_VERIFIED):
            if self.value is None:
                raise StatusInvariantViolation(
                    f"{self.field}: status {status.value} requires a value. An absent "
                    "value must be recorded as 'missing' with a reason."
                )
            if self.provenance is None:
                raise ProvenanceRequired(
                    f"{self.field}: a value may not be recorded without a source "
                    "(doc_id, page, char_span)."
                )

        elif status is FactStatus.MISSING:
            if self.value is not None:
                raise StatusInvariantViolation(
                    f"{self.field}: status 'missing' cannot carry a value."
                )
            if not self.reason:
                raise StatusInvariantViolation(
                    f"{self.field}: status 'missing' requires a reason, so the gap "
                    "explains itself in the interface."
                )

        elif status is FactStatus.CONFLICTED:
            if len(self.conflict) < 2:
                raise StatusInvariantViolation(
                    f"{self.field}: status 'conflicted' requires at least two sources."
                )

        elif status is FactStatus.REGIME_DEFAULT:
            if self.value is None:
                raise StatusInvariantViolation(
                    f"{self.field}: status 'regime_default' requires a value."
                )
            if not self.regime:
                raise StatusInvariantViolation(
                    f"{self.field}: status 'regime_default' must name the regime it came "
                    "from, so the interface never implies the letter stated it."
                )
            if self.provenance is not None:
                raise StatusInvariantViolation(
                    f"{self.field}: a regime default has no document source by definition."
                )

        elif status is FactStatus.NOT_APPLICABLE:
            if self.value is not None:
                raise StatusInvariantViolation(
                    f"{self.field}: status 'not_applicable' cannot carry a value."
                )

        elif status is FactStatus.HUMAN_ANSWERED:
            if self.value is None:
                raise StatusInvariantViolation(
                    f"{self.field}: status 'human_answered' requires a value."
                )
            if not self.verified_by:
                raise StatusInvariantViolation(
                    f"{self.field}: a human answer must name the person who gave it."
                )
            spec = get_field(self.field)
            if spec is not None and spec.origin.value == "engine":
                raise StatusInvariantViolation(
                    f"{self.field}: computed fields cannot be stated by a person; correct "
                    "the facts they are computed from instead."
                )

        if status is FactStatus.HUMAN_VERIFIED and not self.verified_by:
            raise StatusInvariantViolation(
                f"{self.field}: status 'human_verified' requires verified_by."
            )

    # -- derived ------------------------------------------------------------------

    @property
    def spec(self) -> FieldSpec:
        spec = get_field(self.field)
        assert spec is not None  # guaranteed by the validator
        return spec

    @property
    def is_known(self) -> bool:
        """Whether the fact carries a usable value at all."""
        return self.status in (
            FactStatus.EXTRACTED,
            FactStatus.HUMAN_VERIFIED,
            FactStatus.HUMAN_ANSWERED,
            FactStatus.REGIME_DEFAULT,
        )

    @property
    def is_packet_ready(self) -> bool:
        """Whether this fact may be relied on in a submission packet.

        Critical fields require human verification. Privilege separation stops an injected
        instruction from acting, but it cannot stop planted text from being extracted as a
        plausible fact; this is where that residual risk is contained.
        """
        if not self.is_known:
            return False
        if self.spec.is_critical:
            return self.status in (FactStatus.HUMAN_VERIFIED, FactStatus.HUMAN_ANSWERED)
        return True


def _check_value_kind(spec: FieldSpec, value: FactValue) -> None:
    """Reject a value whose shape does not match the field's declared kind."""
    kind = spec.kind

    if kind is FactKind.BOOL:
        if not isinstance(value, bool):
            raise FactTypeMismatch(f"{spec.name}: expected a boolean, got {type(value).__name__}")

    elif kind is FactKind.INT:
        if isinstance(value, bool) or not isinstance(value, int):
            raise FactTypeMismatch(f"{spec.name}: expected an integer, got {type(value).__name__}")

    elif kind is FactKind.DATE:
        if not isinstance(value, str):
            raise FactTypeMismatch(f"{spec.name}: expected an ISO date string")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise FactTypeMismatch(
                f"{spec.name}: {value!r} is not an ISO-8601 calendar date"
            ) from exc

    elif kind is FactKind.STRING:
        if not isinstance(value, str) or isinstance(value, bool):
            raise FactTypeMismatch(f"{spec.name}: expected a string, got {type(value).__name__}")
        if not value.strip():
            raise FactTypeMismatch(f"{spec.name}: an empty string is not a value; use 'missing'")

    elif kind is FactKind.STRING_LIST:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise FactTypeMismatch(f"{spec.name}: expected a list of strings")
        if not value:
            raise FactTypeMismatch(f"{spec.name}: an empty list is not a value; use 'missing'")


class Document(BaseModel):
    """A file attached to a case.

    ``trust_zone`` travels with the document rather than being inferred at read time, so
    an agent that must not see raw content cannot be handed it by accident.
    """

    model_config = ConfigDict(frozen=True)

    doc_id: str
    kind: str = Field(description="denial_letter, policy, clinical_notes, ...")
    filename: str
    pages: int = Field(ge=1)
    ingest_method: Literal["text", "ocr"] = "text"
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    trust_zone: TrustZone = TrustZone.UNTRUSTED
    sha256: str
    ingested_at: datetime = Field(default_factory=utcnow)


class StateTransition(BaseModel):
    """One recorded move of the case state machine.

    Every transition is logged so the trace can answer 'why is this case here' without
    re-running anything.
    """

    model_config = ConfigDict(frozen=True)

    from_state: CaseState | None
    to_state: CaseState
    at: datetime = Field(default_factory=utcnow)
    by: str
    reason: str


class EscalationAnswer(BaseModel):
    """A person's reply to one escalation. Answered questions are not asked again."""

    model_config = ConfigDict(frozen=True)

    escalation_id: str
    answer: str
    by: str
    at: datetime = Field(default_factory=utcnow)


class Case(BaseModel):
    """One denial file."""

    model_config = ConfigDict(validate_assignment=True)

    case_id: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    state: CaseState = CaseState.INTAKE
    rule_pack: str | None = Field(
        default=None, description="Selected pack and version, e.g. medical_necessity@1.2.0"
    )
    documents: list[Document] = Field(default_factory=list)
    facts: dict[str, Fact] = Field(default_factory=dict)
    history: list[StateTransition] = Field(default_factory=list)
    answers: dict[str, EscalationAnswer] = Field(default_factory=dict)

    def document(self, doc_id: str) -> Document | None:
        return next((d for d in self.documents if d.doc_id == doc_id), None)

    def fact(self, field: str) -> Fact | None:
        return self.facts.get(field)

    def value(self, field: str) -> FactValue:
        """Return a fact's value, or ``None`` if it is not known.

        Deliberately collapses every not-known status to ``None``: callers in the
        deterministic layer should branch on absence, and consult the :class:`Fact` itself
        when they need to know *why* something is absent.
        """
        fact = self.facts.get(field)
        return fact.value if fact and fact.is_known else None
