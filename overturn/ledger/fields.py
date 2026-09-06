"""The fact taxonomy.

Every field the ledger will ever hold is declared here, with three properties that the
rest of the system relies on:

``kind``
    What shape the value must take. A date field cannot hold the string "soon".

``origin``
    *Who is entitled to write it.* This is a security boundary, not documentation. The
    extraction agent reads untrusted document text; it may write only fields whose origin
    is ``DOCUMENT``. It is structurally incapable of writing a deadline, because deadline
    fields are ``ENGINE`` origin and the extraction tool refuses them.

``criticality``
    Whether a value may be relied on while still only ``extracted``. Privilege separation
    prevents an injected instruction from *acting*, but it cannot prevent planted text
    from being extracted as a plausible fact. Fields marked ``CRITICAL`` are the ones
    where that would change the outcome, so they require human verification before they
    can enter a submission packet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FactKind(StrEnum):
    """The value shape a field accepts."""

    STRING = "string"
    DATE = "date"  # ISO-8601 calendar date, e.g. "2026-08-01"
    BOOL = "bool"
    INT = "int"
    STRING_LIST = "string_list"


class FieldOrigin(StrEnum):
    """Who is entitled to write the field."""

    DOCUMENT = "document"
    """Extractable from a document by the extraction agent, with provenance."""

    ENGINE = "engine"
    """Computed by the deterministic layer. No model may write these, ever."""

    HUMAN = "human"
    """Only a person can answer. No document settles it, so asking is the only route."""


class Criticality(StrEnum):
    """How much trust a value carries before a human has looked at it."""

    NORMAL = "normal"

    CRITICAL = "critical"
    """Materially changes the outcome. Must be ``human_verified`` to enter a packet."""


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    kind: FactKind
    origin: FieldOrigin
    description: str
    pii: bool = False
    criticality: Criticality = Criticality.NORMAL

    @property
    def is_critical(self) -> bool:
        return self.criticality is Criticality.CRITICAL


def _f(
    name: str,
    kind: FactKind,
    origin: FieldOrigin,
    description: str,
    *,
    pii: bool = False,
    critical: bool = False,
) -> FieldSpec:
    return FieldSpec(
        name=name,
        kind=kind,
        origin=origin,
        description=description,
        pii=pii,
        criticality=Criticality.CRITICAL if critical else Criticality.NORMAL,
    )


_D = FieldOrigin.DOCUMENT
_E = FieldOrigin.ENGINE
_H = FieldOrigin.HUMAN

_SPECS: tuple[FieldSpec, ...] = (
    # --- patient -----------------------------------------------------------------
    _f("patient.name", FactKind.STRING, _D, "Patient full name as written", pii=True),
    _f("patient.dob", FactKind.DATE, _D, "Patient date of birth", pii=True),
    _f("patient.member_id", FactKind.STRING, _D, "Insurance member identifier", pii=True),
    _f(
        "patient.relationship_to_policyholder",
        FactKind.STRING,
        _D,
        "Self, spouse, or dependent",
        pii=True,
    ),
    # --- plan --------------------------------------------------------------------
    _f("plan.issuer", FactKind.STRING, _D, "Insurance company issuing the plan"),
    _f("plan.name", FactKind.STRING, _D, "Plan name as printed"),
    _f("plan.type", FactKind.STRING, _D, "HMO, PPO, EPO, POS, Medicare Advantage"),
    _f("plan.grandfathered", FactKind.BOOL, _D, "Grandfathered plan under the ACA"),
    _f("plan.group_or_individual", FactKind.STRING, _D, "Group or individual market"),
    _f("plan.policy_doc_id", FactKind.STRING, _D, "Document holding the policy terms"),
    _f(
        "plan.covers_service",
        FactKind.BOOL,
        _D,
        "Whether the policy covers the denied service",
        critical=True,
    ),
    # --- denial ------------------------------------------------------------------
    _f(
        "denial.notice_date",
        FactKind.DATE,
        _D,
        "Date printed on the denial notice. Starts the appeal clock.",
        critical=True,
    ),
    _f("denial.received_date", FactKind.DATE, _D, "Date the notice was received"),
    _f("denial.reason_text", FactKind.STRING, _D, "Denial reason, verbatim"),
    _f("denial.reason_code", FactKind.STRING, _D, "Payer reason code, e.g. CO-50"),
    _f(
        "denial.cited_policy_section",
        FactKind.STRING,
        _D,
        "Policy clause the denial relies on",
    ),
    _f("denial.level", FactKind.STRING, _D, "initial, internal_appeal, or external_review"),
    _f(
        "denial.is_final",
        FactKind.BOOL,
        _D,
        "Whether this is a final adverse determination. Opens external review.",
        critical=True,
    ),
    _f(
        "denial.stated_appeal_deadline",
        FactKind.DATE,
        _D,
        "Deadline printed in the letter itself. Always beats the statutory default.",
        critical=True,
    ),
    # --- service -----------------------------------------------------------------
    _f("service.description", FactKind.STRING, _D, "The service or item denied"),
    _f("service.cpt_codes", FactKind.STRING_LIST, _D, "CPT or HCPCS codes"),
    _f("service.date_of_service", FactKind.DATE, _D, "Date the service was rendered"),
    _f(
        "service.is_pre_service",
        FactKind.BOOL,
        _D,
        "Denial issued before the service was rendered. Changes the response window.",
        critical=True,
    ),
    _f(
        "service.was_prior_auth_obtained",
        FactKind.BOOL,
        _D,
        "Whether prior authorization was obtained",
    ),
    _f("service.provider_in_network", FactKind.BOOL, _D, "Provider is in network"),
    _f(
        "service.was_urgent",
        FactKind.BOOL,
        _H,
        "Whether the service was urgent. A clinical and factual judgment: no document "
        "settles it, so the system asks rather than infers.",
        critical=True,
    ),
    # --- provider ----------------------------------------------------------------
    _f("provider.name", FactKind.STRING, _D, "Treating provider or facility"),
    _f("provider.npi", FactKind.STRING, _D, "National Provider Identifier"),
    _f("provider.is_treating_physician", FactKind.BOOL, _D, "Author is the treating physician"),
    # --- deadlines (engine only) -------------------------------------------------
    _f(
        "deadline.internal_appeal_due",
        FactKind.DATE,
        _E,
        "Last day to file the internal appeal",
        critical=True,
    ),
    _f(
        "deadline.external_review_due",
        FactKind.DATE,
        _E,
        "Last day to request external review",
        critical=True,
    ),
    _f(
        "deadline.plan_response_due",
        FactKind.DATE,
        _E,
        "Date by which the plan must respond",
        critical=True,
    ),
)

FIELDS: dict[str, FieldSpec] = {spec.name: spec for spec in _SPECS}

EVIDENCE_PREFIX = "evidence."
"""Evidence fields are declared by rule packs rather than here. They are booleans:
``evidence.<evidence_id>`` records whether that piece of evidence is on file."""


def get_field(name: str) -> FieldSpec | None:
    """Return the spec for ``name``, resolving dynamic ``evidence.*`` fields.

    Returns ``None`` for anything not in the taxonomy. Callers must treat that as a
    refusal: accepting unknown field names would let planted text invent a field that
    downstream code happens to read.
    """
    spec = FIELDS.get(name)
    if spec is not None:
        return spec
    if name.startswith(EVIDENCE_PREFIX) and len(name) > len(EVIDENCE_PREFIX):
        return FieldSpec(
            name=name,
            kind=FactKind.BOOL,
            origin=FieldOrigin.DOCUMENT,
            description="Rule-pack declared evidence item present on file",
        )
    return None


def pii_fields() -> frozenset[str]:
    """Fields that must be masked in logs and traces."""
    return frozenset(name for name, spec in FIELDS.items() if spec.pii)


def critical_fields() -> frozenset[str]:
    """Fields that require human verification before entering a submission packet."""
    return frozenset(name for name, spec in FIELDS.items() if spec.is_critical)
