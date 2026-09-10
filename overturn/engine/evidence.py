"""What this case still needs, and whether a packet can be assembled.

Deterministic. Given a rule pack and a ledger, this answers three questions an advocate
actually asks: what is missing, which of it only a person can get, and whether the file
can go out.

The distinction that matters is between *absent* and *unverified*. A critical fact that
was extracted with a perfectly good citation is still not something a packet may rest on,
because privilege separation does not stop planted text from being extracted. Those facts
appear here as their own category — not missing, not ready — and the interface asks a
person to confirm them rather than treating the citation as sufficient.
"""

from __future__ import annotations

from dataclasses import dataclass

from overturn.engine.packs import EvidenceItem, RulePack
from overturn.ledger.schema import Case, FactStatus


@dataclass(frozen=True, slots=True)
class FactGap:
    """A required fact the packet cannot proceed without, and why."""

    field: str
    status: FactStatus | None
    reason: str
    human_only: bool = False

    @property
    def is_conflict(self) -> bool:
        return self.status is FactStatus.CONFLICTED


@dataclass(frozen=True, slots=True)
class Readiness:
    """Everything the case needs, sorted by what a person can do about it."""

    pack: RulePack

    present_evidence: tuple[EvidenceItem, ...]
    missing_blocking_evidence: tuple[EvidenceItem, ...]
    missing_optional_evidence: tuple[EvidenceItem, ...]

    fact_gaps: tuple[FactGap, ...]
    unverified_critical_facts: tuple[str, ...]

    @property
    def human_only_gaps(self) -> tuple[EvidenceItem, ...]:
        """Missing evidence no agent can obtain. Raises escalation trigger 1."""
        return tuple(
            item
            for item in self.missing_blocking_evidence + self.missing_optional_evidence
            if item.human_only
        )

    @property
    def conflicts(self) -> tuple[FactGap, ...]:
        """Fields where two sources disagree. Often an argument, not just a problem."""
        return tuple(gap for gap in self.fact_gaps if gap.is_conflict)

    @property
    def is_packet_ready(self) -> bool:
        """Whether the appeal can be assembled and handed to a person to send."""
        return (
            not self.missing_blocking_evidence
            and not self.fact_gaps
            and not self.unverified_critical_facts
        )

    @property
    def blocking_count(self) -> int:
        return (
            len(self.missing_blocking_evidence)
            + len(self.fact_gaps)
            + len(self.unverified_critical_facts)
        )

    def summary(self) -> str:
        """One line, in the register the interface uses: what is needed, not how it feels."""
        if self.is_packet_ready:
            return f"Packet ready under {self.pack.display_name}."
        parts = []
        if self.missing_blocking_evidence:
            parts.append(f"{len(self.missing_blocking_evidence)} required document(s) not on file")
        if self.fact_gaps:
            parts.append(f"{len(self.fact_gaps)} required fact(s) unresolved")
        if self.unverified_critical_facts:
            parts.append(f"{len(self.unverified_critical_facts)} critical fact(s) unverified")
        return f"{self.pack.display_name}: " + ", ".join(parts) + "."


def assess(case: Case, pack: RulePack) -> Readiness:
    """Compare the ledger against what the pack requires."""
    present: list[EvidenceItem] = []
    missing_blocking: list[EvidenceItem] = []
    missing_optional: list[EvidenceItem] = []

    for item in pack.required_evidence:
        fact = case.fact(item.fact_field)
        if fact is not None and fact.is_known and fact.value is True:
            present.append(item)
        elif item.blocking:
            missing_blocking.append(item)
        else:
            missing_optional.append(item)

    fact_gaps: list[FactGap] = []
    unverified: list[str] = []

    for field in pack.required_facts:
        fact = case.fact(field)

        if fact is None:
            fact_gaps.append(
                FactGap(
                    field=field,
                    status=None,
                    reason="Not yet looked for. No document has been read for this field.",
                )
            )
            continue

        if fact.status is FactStatus.MISSING:
            fact_gaps.append(
                FactGap(
                    field=field,
                    status=fact.status,
                    reason=fact.reason or "No source found in the documents on file.",
                    human_only=fact.spec.origin.value == "human",
                )
            )
            continue

        if fact.status is FactStatus.CONFLICTED:
            fact_gaps.append(
                FactGap(
                    field=field,
                    status=fact.status,
                    reason=(
                        "Two documents disagree. A person decides which reading the "
                        "appeal proceeds on; the contradiction itself may be an argument."
                    ),
                )
            )
            continue

        if fact.status is FactStatus.NOT_APPLICABLE:
            fact_gaps.append(
                FactGap(
                    field=field,
                    status=fact.status,
                    reason=(
                        "Marked not applicable, but this pack requires it. The "
                        "classification and the ledger disagree."
                    ),
                )
            )
            continue

        if not fact.is_packet_ready:
            # Known, sourced, and still not enough: a critical field awaiting a person.
            unverified.append(field)

    # A critical fact the pack does not list still changes the outcome: whether a
    # decision is final moves the whole case to external review and changes every
    # deadline. Found by the red-team suite, where a planted 'final determination'
    # line was recorded with a genuine citation and nobody was asked to check it.
    for name, fact in case.facts.items():
        if name in unverified or name in pack.required_facts:
            continue
        if fact.spec.is_critical and fact.status is FactStatus.EXTRACTED:
            unverified.append(name)

    return Readiness(
        pack=pack,
        present_evidence=tuple(present),
        missing_blocking_evidence=tuple(missing_blocking),
        missing_optional_evidence=tuple(missing_optional),
        fact_gaps=tuple(fact_gaps),
        unverified_critical_facts=tuple(unverified),
    )
