"""The escalation gate: the only place the system is allowed to interrupt a person.

Four triggers. The list is closed, published in the README, and enforced here — there is
no general-purpose "notify the user" path anywhere in the codebase. Everything else that
happens to a case is logged and visible on demand, and interrupts nobody.

Two properties make this usable rather than merely principled.

**Escalations are idempotent.** The background scheduler runs every fifteen minutes. An
escalation's identity is derived from what it is about, not from when it was raised, so the
same unanswered question is the same escalation on the ninety-sixth tick as on the first.
A system that asks the same question every quarter of an hour is one the advocate turns
off, and a system they turn off protects nobody.

**Every escalation says why it matters.** Not as a courtesy: the advocate is being asked to
spend attention, and the reason is what lets them decide whether to spend it now. It is
also what stops the tool from sounding like it is issuing orders to the person it works
for.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum

from overturn.engine.anomalies import Anomaly
from overturn.engine.deadlines import DeadlineComputation, Pressure
from overturn.engine.evidence import Readiness
from overturn.engine.rules import Classification
from overturn.ledger.schema import Case


class Trigger(IntEnum):
    """The closed list. Adding a fifth is a product decision, not a code change."""

    HUMAN_ONLY_DOCUMENT = 1
    """Something only a person can obtain is missing."""

    HUMAN_JUDGMENT = 2
    """A factual or clinical judgment no document settles."""

    DEADLINE_PRESSURE = 3
    """A deadline threshold was crossed."""

    DOCUMENT_ANOMALY = 4
    """Something is wrong with an incoming document."""

    @property
    def label(self) -> str:
        return {
            Trigger.HUMAN_ONLY_DOCUMENT: "human_only_document",
            Trigger.HUMAN_JUDGMENT: "human_judgment_required",
            Trigger.DEADLINE_PRESSURE: "deadline_pressure",
            Trigger.DOCUMENT_ANOMALY: "document_anomaly",
        }[self]


@dataclass(frozen=True, slots=True)
class Escalation:
    """One question put to a person, with the reason it is worth their attention."""

    escalation_id: str
    case_id: str
    trigger: Trigger
    question: str
    why_it_matters: str
    subject: str
    """What this is about: a field name, an evidence id, or a deadline field."""
    options: tuple[str, ...] = ()
    blocking: bool = True
    detail: str | None = None

    @property
    def trigger_label(self) -> str:
        return self.trigger.label


@dataclass(frozen=True, slots=True)
class GateResult:
    escalations: tuple[Escalation, ...]
    silent: tuple[str, ...] = field(default_factory=tuple)
    """Everything noted but deliberately not raised. Visible on demand, notified never."""

    def by_trigger(self, trigger: Trigger) -> tuple[Escalation, ...]:
        return tuple(e for e in self.escalations if e.trigger is trigger)

    @property
    def blocking(self) -> tuple[Escalation, ...]:
        return tuple(e for e in self.escalations if e.blocking)


def escalation_id(case_id: str, trigger: Trigger, subject: str) -> str:
    """A stable identity for 'this question, about this thing, on this case'.

    Deliberately excludes the time it was raised. Re-running the gate on an unchanged case
    produces the same ids, so answering a question makes it stay answered.
    """
    digest = hashlib.sha256(f"{case_id}|{int(trigger)}|{subject}".encode()).hexdigest()
    return f"esc_{digest[:12]}"


def evaluate(
    case: Case,
    *,
    classification: Classification | None = None,
    readiness: Readiness | None = None,
    deadlines: DeadlineComputation | None = None,
    anomalies: tuple[Anomaly, ...] = (),
    today: date | None = None,
    resolved: frozenset[str] = frozenset(),
) -> GateResult:
    """Run the gate over the current state of a case.

    Pure: takes the deterministic layer's outputs and returns what a person should be
    asked. Nothing here notifies, writes or advances the case.

    Args:
        resolved: escalation ids a person has already answered. Answered questions are not
            re-asked, which is what makes the fifteen-minute tick tolerable.
    """
    today = today or date.today()
    raised: list[Escalation] = []
    silent: list[str] = []

    raised.extend(_deadline_escalations(case, deadlines, today, silent))
    raised.extend(_judgment_escalations(case, classification, readiness, silent))
    raised.extend(_document_escalations(case, readiness, silent))
    raised.extend(_anomaly_escalations(case, anomalies, silent))

    kept = tuple(e for e in raised if e.escalation_id not in resolved)
    suppressed = len(raised) - len(kept)
    if suppressed:
        silent.append(f"{suppressed} escalation(s) already answered and not re-raised.")

    kept = tuple(sorted(kept, key=lambda e: (int(e.trigger), e.subject)))
    return GateResult(escalations=kept, silent=tuple(silent))


# --- trigger 3: deadline pressure ------------------------------------------------------


def _deadline_escalations(
    case: Case,
    deadlines: DeadlineComputation | None,
    today: date,
    silent: list[str],
) -> list[Escalation]:
    if deadlines is None:
        return []

    out: list[Escalation] = []
    for deadline in deadlines.deadlines:
        if deadline.met_on is not None:
            # A window a person has already met is not pressing, however close its date.
            silent.append(
                f"{deadline.field} met: the appeal is recorded as filed on "
                f"{deadline.met_on.isoformat()}."
            )
            continue
        pressure = deadline.pressure(today)
        remaining = deadline.days_remaining(today)

        if not pressure.escalates:
            if pressure is Pressure.INFO:
                silent.append(
                    f"{deadline.field} is {remaining} days out; visible on the timeline, "
                    "not notified."
                )
            continue

        basis_note = (
            "This date is printed in the notice."
            if deadline.basis.value == "stated_in_letter"
            else (
                f"This date is the statutory default ({deadline.rule}); the notice did not "
                "state one."
            )
        )
        if deadline.anchor_is_estimated:
            basis_note += (
                " The receipt date is unknown, so the notice date was used, which makes "
                "this the earliest possible deadline rather than the exact one."
            )

        if deadline.field == "deadline.plan_response_due":
            # After filing, the clock that matters is the plan's, not the advocate's.
            question = f"The plan's decision is due {_when(remaining)}. Has it arrived?"
            why = (
                "A plan that misses its own response deadline may be treated as having "
                "exhausted its internal process, which can open external review without "
                "further waiting. Worth checking against the plan's terms. " + basis_note
            )
            options = ("Decision received", "Still waiting")
        elif pressure is Pressure.EXPIRED:
            question = (
                f"{_deadline_name(deadline.field).capitalize()} passed "
                f"{abs(remaining)} day(s) ago. How should this case proceed?"
            )
            why = (
                "Filing after the window usually ends the internal route, but a stated "
                "date can be wrong and some plans accept late filings for good cause. " + basis_note
            )
            options = ("File anyway", "Move to external review", "Close the case")
        else:
            question = (
                f"{_deadline_name(deadline.field).capitalize()} is {remaining} day(s) "
                "away. Is this case on track to be filed?"
            )
            why = (
                "This is the deadline the whole file depends on; missing it ends the "
                "appeal on procedure rather than on the merits. " + basis_note
            )
            options = ("On track", "Needs attention today", "Reassign")

        out.append(
            Escalation(
                escalation_id=escalation_id(
                    case.case_id, Trigger.DEADLINE_PRESSURE, f"{deadline.field}:{pressure.value}"
                ),
                case_id=case.case_id,
                trigger=Trigger.DEADLINE_PRESSURE,
                subject=deadline.field,
                question=question,
                why_it_matters=why,
                options=options,
                blocking=pressure in (Pressure.CRITICAL, Pressure.EXPIRED),
                detail=f"due {deadline.due.isoformat()} ({deadline.rule})",
            )
        )

    for blocked in deadlines.blocked:
        if "denial.notice_date" in blocked.missing_fields:
            out.append(
                Escalation(
                    escalation_id=escalation_id(
                        case.case_id, Trigger.DEADLINE_PRESSURE, blocked.field
                    ),
                    case_id=case.case_id,
                    trigger=Trigger.DEADLINE_PRESSURE,
                    subject=blocked.field,
                    question="What date is on the denial notice?",
                    why_it_matters=(
                        "No date starts the appeal clock, so no deadline can be computed "
                        "for this case at all. Until it is known, this file is running "
                        "against a clock nobody can see."
                    ),
                    blocking=True,
                    detail=blocked.explanation,
                )
            )
        else:
            silent.append(f"{blocked.field} not computable: {blocked.explanation}")

    return out


# --- trigger 2: human judgment -----------------------------------------------------------


def _judgment_escalations(
    case: Case,
    classification: Classification | None,
    readiness: Readiness | None,
    silent: list[str],
) -> list[Escalation]:
    out: list[Escalation] = []

    if classification is not None and classification.ambiguous:
        names = ", ".join(c.pack.display_name for c in classification.candidates[:3])
        out.append(
            Escalation(
                escalation_id=escalation_id(case.case_id, Trigger.HUMAN_JUDGMENT, "classification"),
                case_id=case.case_id,
                trigger=Trigger.HUMAN_JUDGMENT,
                subject="classification",
                question=f"This notice cites more than one denial reason. Which does the "
                f"appeal answer: {names}?",
                why_it_matters=(
                    "An appeal that argues against a reason the plan did not lead with is "
                    "one of the most common ways a winnable file is lost. The system will "
                    "not guess between them."
                ),
                options=tuple(c.pack.display_name for c in classification.candidates[:3]),
                blocking=True,
                detail=classification.explanation,
            )
        )

    for field_name in _human_judgment_fields(case, readiness):
        question, why = _JUDGMENT_QUESTIONS.get(
            field_name,
            (
                f"What is the correct value for {_human(field_name)}?",
                "No document on file establishes it, and it is required for this appeal.",
            ),
        )
        out.append(
            Escalation(
                escalation_id=escalation_id(case.case_id, Trigger.HUMAN_JUDGMENT, field_name),
                case_id=case.case_id,
                trigger=Trigger.HUMAN_JUDGMENT,
                subject=field_name,
                question=question,
                why_it_matters=why,
                options=("Yes", "No", "Not sure"),
                blocking=True,
            )
        )

    if readiness is not None:
        for gap in readiness.conflicts:
            out.append(
                Escalation(
                    escalation_id=escalation_id(
                        case.case_id, Trigger.HUMAN_JUDGMENT, f"conflict:{gap.field}"
                    ),
                    case_id=case.case_id,
                    trigger=Trigger.HUMAN_JUDGMENT,
                    subject=gap.field,
                    question=(
                        f"Two documents disagree about {_human(gap.field)}. Which reading "
                        "should the appeal proceed on?"
                    ),
                    why_it_matters=(
                        "The contradiction may itself be the strongest argument in the "
                        "file, but the appeal has to take a position on it."
                    ),
                    blocking=True,
                    detail=gap.reason,
                )
            )

        for field_name in readiness.unverified_critical_facts:
            out.append(
                Escalation(
                    escalation_id=escalation_id(
                        case.case_id, Trigger.HUMAN_JUDGMENT, f"verify:{field_name}"
                    ),
                    case_id=case.case_id,
                    trigger=Trigger.HUMAN_JUDGMENT,
                    subject=field_name,
                    question=(
                        f"Please confirm {_human(field_name)} against the original document."
                    ),
                    why_it_matters=(
                        "This field changes the outcome, and a value read from a document "
                        "is not confirmation that the document is honest. Critical fields "
                        "are checked by a person before a packet is assembled."
                    ),
                    options=("Confirm", "Correct it"),
                    blocking=True,
                )
            )

    return out


def _human_judgment_fields(case: Case, readiness: Readiness | None) -> list[str]:
    """Required fields that only a person can answer and that are still unanswered."""
    if readiness is None:
        return []
    out = []
    for gap in readiness.fact_gaps:
        spec_origin = None
        spec = case.fact(gap.field).spec if case.fact(gap.field) else None
        if spec is not None:
            spec_origin = spec.origin.value
        if gap.human_only or spec_origin == "human":
            out.append(gap.field)
    return out


_JUDGMENT_QUESTIONS: dict[str, tuple[str, str]] = {
    "service.was_urgent": (
        "Was this service obtained in an urgent situation?",
        "If it was urgent, a prior authorization exception may apply and the plan's "
        "response window drops from days to 72 hours. It changes both the argument and the "
        "clock, and no document on file settles it.",
    ),
    "appeal.filed_date": (
        "Has this appeal been filed, and on what date?",
        "The plan's response deadline runs from the filing date. Overturn never submits "
        "anything itself, so it only knows this happened if you record it.",
    ),
}


# --- trigger 1: documents only a person can obtain -----------------------------------------


def _document_escalations(
    case: Case, readiness: Readiness | None, silent: list[str]
) -> list[Escalation]:
    if readiness is None:
        return []

    out: list[Escalation] = []
    for item in readiness.human_only_gaps:
        out.append(
            Escalation(
                escalation_id=escalation_id(case.case_id, Trigger.HUMAN_ONLY_DOCUMENT, item.id),
                case_id=case.case_id,
                trigger=Trigger.HUMAN_ONLY_DOCUMENT,
                subject=item.id,
                question=f"Please request: {item.label}",
                why_it_matters=(
                    f"This document has to come from {item.source.replace('_', ' ')}, and "
                    "no part of this system can obtain it. "
                    + (
                        "The packet cannot be assembled without it."
                        if item.blocking
                        else "The appeal can proceed without it, but it is materially "
                        "stronger with it."
                    )
                ),
                blocking=item.blocking,
            )
        )

    ordinary = [item for item in readiness.missing_blocking_evidence if not item.human_only]
    if ordinary:
        silent.append(
            f"{len(ordinary)} required document(s) still to be collected: "
            + ", ".join(i.id for i in ordinary)
        )

    return out


# --- trigger 4: document anomalies ------------------------------------------------------


def _anomaly_escalations(
    case: Case, anomalies: tuple[Anomaly, ...], silent: list[str]
) -> list[Escalation]:
    out: list[Escalation] = []
    for anomaly in anomalies:
        if not anomaly.escalates:
            silent.append(f"{anomaly.kind.value} in {anomaly.doc_id}: {anomaly.excerpt}")
            continue

        subject = f"{anomaly.doc_id}:{anomaly.kind.value}:{anomaly.page or 0}"
        out.append(
            Escalation(
                escalation_id=escalation_id(case.case_id, Trigger.DOCUMENT_ANOMALY, subject),
                case_id=case.case_id,
                trigger=Trigger.DOCUMENT_ANOMALY,
                subject=subject,
                question=(
                    f"A document on this case contains something unexpected. Review "
                    f"{anomaly.doc_id}" + (f", page {anomaly.page}" if anomaly.page else "") + "."
                ),
                why_it_matters=(
                    anomaly.explanation
                    + " No agent acted on it: the agent that reads document text holds no "
                    "tools that could. You are being told because the document itself is "
                    "now a question."
                ),
                options=("Reviewed, continue", "Quarantine this document"),
                blocking=False,
                detail=anomaly.excerpt,
            )
        )
    return out


_DEADLINE_NAMES = {
    "deadline.internal_appeal_due": "the internal appeal deadline",
    "deadline.external_review_due": "the external review deadline",
    "deadline.plan_response_due": "the plan's response deadline",
}


def _deadline_name(field_name: str) -> str:
    return _DEADLINE_NAMES.get(field_name, _human(field_name))


def _when(days: int) -> str:
    if days > 0:
        return f"in {days} day(s)"
    return "today" if days == 0 else f"{-days} day(s) ago"


_FIELD_NAMES = {
    "denial.notice_date": "the notice date",
    "denial.received_date": "the date the notice was received",
    "denial.is_final": "whether this is a final decision",
    "denial.stated_appeal_deadline": "the appeal deadline printed in the letter",
    "denial.reason_text": "the denial reason",
    "denial.cited_policy_section": "the policy section the denial cites",
    "service.is_pre_service": "whether the plan decided before the service was given",
    "service.was_urgent": "whether the service was urgent",
    "plan.covers_service": "whether the plan covers this service",
    "appeal.filed_date": "the filing date",
    "provider.is_treating_physician": "whether the treating physician wrote the letter",
}
"""How the fields a person may be asked about read in a sentence."""


def _human(field_name: str) -> str:
    """Turn a field name into something readable in a sentence."""
    if field_name in _FIELD_NAMES:
        return _FIELD_NAMES[field_name]
    return field_name.split(".", 1)[-1].replace("_", " ")
