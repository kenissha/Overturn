"""Argument planning: which paragraphs the appeal may contain, filled from the ledger.

This is the drafting layer's contract. Every paragraph in an appeal comes from a step in
the rule pack's argument skeleton, and a step is written only when every fact it names is
known and every document it relies on is on file. A step that cannot be supported is
**omitted and reported**, never softened into a vaguer claim the ledger cannot back.

Placeholders are filled directly from ledger values, so the letter assembled here is
complete without any model at all. A model may later rewrite it for flow — from this plan
and nothing else, never from the documents — but nothing in the appeal depends on that
step, and nothing it adds can introduce a fact.

Each rendered paragraph carries citations: the ledger facts it was built from, with their
provenance. That is what lets the interface show, beside every sentence of the draft, the
line of the letter that justifies it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from overturn.engine.packs import ArgumentStep, RulePack, placeholders
from overturn.ledger.fields import FactKind
from overturn.ledger.schema import Case, FactStatus, Provenance

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True, slots=True)
class Citation:
    """One ledger fact a paragraph was built from."""

    field: str
    value_text: str
    status: FactStatus
    provenance: Provenance | None
    critical: bool

    @property
    def verified(self) -> bool:
        return self.status is FactStatus.HUMAN_VERIFIED


@dataclass(frozen=True, slots=True)
class RenderedStep:
    step_id: str
    text: str
    citations: tuple[Citation, ...]
    evidence: tuple[str, ...]

    @property
    def rests_on_unverified(self) -> bool:
        """Built on a critical fact a person has not yet confirmed.

        The paragraph is still shown, so the advocate can read the draft as it will be,
        but the interface marks it and the packet stays blocked until the fact is checked.
        """
        return any(c.critical and not c.verified for c in self.citations)


@dataclass(frozen=True, slots=True)
class OmittedStep:
    step_id: str
    reason: str
    missing_facts: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    condition_unmet: bool = False

    @property
    def is_gap(self) -> bool:
        """Whether this omission is something to fix, rather than a branch not taken."""
        return not self.condition_unmet


@dataclass(frozen=True, slots=True)
class ArgumentPlan:
    pack: RulePack
    included: tuple[RenderedStep, ...]
    omitted: tuple[OmittedStep, ...]

    @property
    def gaps(self) -> tuple[OmittedStep, ...]:
        return tuple(step for step in self.omitted if step.is_gap)

    def step(self, step_id: str) -> RenderedStep | None:
        return next((s for s in self.included if s.step_id == step_id), None)


def plan_argument(case: Case, pack: RulePack) -> ArgumentPlan:
    """Decide, step by step, what the appeal is entitled to say."""
    included: list[RenderedStep] = []
    omitted: list[OmittedStep] = []

    for step in pack.argument_skeleton:
        if step.condition is not None and not step.condition.holds_for(case):
            omitted.append(
                OmittedStep(
                    step_id=step.id,
                    reason=f"Only applies when {step.condition.fact} is "
                    + (
                        step.condition.status_is.value
                        if step.condition.status_is is not None
                        else repr(step.condition.value_is)
                    )
                    + ".",
                    condition_unmet=True,
                )
            )
            continue

        missing_facts = tuple(f for f in _required_facts(step) if not _known(case, f))
        missing_evidence = tuple(
            e for e in step.requires_evidence if case.value(f"evidence.{e}") is not True
        )
        if missing_facts or missing_evidence:
            omitted.append(
                OmittedStep(
                    step_id=step.id,
                    reason=_omission_reason(missing_facts, missing_evidence, pack),
                    missing_facts=missing_facts,
                    missing_evidence=missing_evidence,
                )
            )
            continue

        included.append(_render(step, case))

    return ArgumentPlan(pack=pack, included=tuple(included), omitted=tuple(omitted))


def render_letter(plan: ArgumentPlan, case: Case) -> str:
    """Assemble the plain-text appeal from the plan. No model involved.

    Headed as a draft for a person to send. Overturn never submits anything, and the
    document says so on its face so it cannot be mistaken for something already filed.
    """
    lines = [
        "DRAFT APPEAL — prepared for review. This letter has not been sent.",
        "",
    ]
    issuer = case.value("plan.issuer")
    member = case.value("patient.member_id")
    if isinstance(issuer, str):
        lines.append(f"To: {issuer}, Appeals Department")
    if isinstance(member, str):
        lines.append(f"Member ID: {member}")
    lines += ["", "Re: Request for internal appeal of an adverse benefit determination", ""]

    for step in plan.included:
        lines += [step.text, ""]

    enclosed = []
    for step in plan.included:
        for evidence_id in step.evidence:
            item = plan.pack.evidence(evidence_id)
            label = item.label if item else evidence_id
            if label not in enclosed:
                enclosed.append(label)
    if enclosed:
        lines.append("Enclosures:")
        lines += [f"- {label}" for label in enclosed]

    return "\n".join(lines).rstrip() + "\n"


# --- internals ----------------------------------------------------------------------------


def _required_facts(step: ArgumentStep) -> tuple[str, ...]:
    """Declared requirements plus every interpolated field.

    A placeholder the pack author forgot to list is still a requirement: a sentence
    cannot be written with a hole in it.
    """
    seen: dict[str, None] = {}
    for name in (*step.requires_facts, *placeholders(step.claim)):
        seen.setdefault(name, None)
    return tuple(seen)


def _known(case: Case, field: str) -> bool:
    fact = case.fact(field)
    return fact is not None and fact.is_known and fact.value is not None


def _render(step: ArgumentStep, case: Case) -> RenderedStep:
    text = " ".join(step.claim.split())
    citations: list[Citation] = []
    for name in _required_facts(step):
        fact = case.fact(name)
        assert fact is not None  # guaranteed by _known
        shown = _display(fact.spec.kind, fact.value)
        text = text.replace("{" + name + "}", shown)
        citations.append(
            Citation(
                field=name,
                value_text=shown,
                status=fact.status,
                provenance=fact.provenance,
                critical=fact.spec.is_critical,
            )
        )
    return RenderedStep(
        step_id=step.id,
        text=text,
        citations=tuple(citations),
        evidence=tuple(step.requires_evidence),
    )


def _display(kind: FactKind, value: object) -> str:
    if kind is FactKind.DATE and isinstance(value, str):
        d = date.fromisoformat(value)
        return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"
    if kind is FactKind.STRING_LIST and isinstance(value, list):
        return ", ".join(value)
    if kind is FactKind.BOOL:
        return "yes" if value else "no"
    return str(value)


def _omission_reason(
    missing_facts: tuple[str, ...], missing_evidence: tuple[str, ...], pack: RulePack
) -> str:
    parts = []
    if missing_facts:
        parts.append("the ledger does not establish " + ", ".join(missing_facts))
    if missing_evidence:
        labels = []
        for evidence_id in missing_evidence:
            item = pack.evidence(evidence_id)
            labels.append(item.label if item else evidence_id)
        parts.append("not on file: " + "; ".join(labels))
    return "Omitted because " + " and ".join(parts) + "."
