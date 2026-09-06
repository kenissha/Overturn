"""Classification: which rule pack applies to this denial.

Deterministic, and matched against grounded facts rather than raw document text. The
classifier never reads a document; it reads what extraction recorded, with the source
still attached.

Two properties matter more than accuracy here.

**It explains itself.** Every decision carries the signals that produced it — which code
matched, which phrase, in which fact, sourced from which page. "It chose medical necessity"
is not an answer an advocate can check; "it chose medical necessity because reason code
CO-50 appeared on page 1" is.

**It declines when it is unsure.** A denial letter citing more than one reason is a real
and common trap, and quietly picking the higher-scoring category would produce an appeal
arguing against a reason the letter did not lead with. When two packs score within a
margin of each other, the classifier selects nothing and hands the choice to a person.
"""

from __future__ import annotations

from dataclasses import dataclass

from overturn.engine.packs import PackRegistry, RulePack
from overturn.ledger.schema import Case, Fact

REASON_CODE_WEIGHT = 1.0
"""An exact payer reason code is the strongest signal available."""

PHRASE_WEIGHT = 0.8
"""Phrasing is reliable but paraphrasable, so it never outranks a code."""

CORROBORATION_BONUS = 0.05
"""Small credit for agreeing signals. Never enough to turn a phrase into a code."""

AMBIGUITY_MARGIN = 0.15
"""How close the runner-up must be before the classifier refuses to choose."""


@dataclass(frozen=True, slots=True)
class MatchSignal:
    """One reason a pack matched, traceable back to the page it came from."""

    kind: str
    detail: str
    source_field: str
    weight: float
    doc_id: str | None = None
    page: int | None = None

    def describe(self) -> str:
        where = f" ({self.doc_id} page {self.page})" if self.doc_id else ""
        return f"{self.detail} in {self.source_field}{where}"


@dataclass(frozen=True, slots=True)
class PackCandidate:
    pack: RulePack
    score: float
    signals: tuple[MatchSignal, ...]

    def describe(self) -> str:
        return f"{self.pack.qualified_name} ({self.score:.2f}): " + "; ".join(
            s.describe() for s in self.signals
        )


@dataclass(frozen=True, slots=True)
class Classification:
    """The result, including the case where the honest answer is 'I am not sure'."""

    selected: RulePack | None
    candidates: tuple[PackCandidate, ...]
    ambiguous: bool
    explanation: str
    blocked_by: tuple[str, ...] = ()

    @property
    def needs_human(self) -> bool:
        """Whether this raises an escalation rather than advancing the case."""
        return self.selected is None


def classify(case: Case, registry: PackRegistry) -> Classification:
    """Select the rule pack that applies, or explain why one cannot be selected."""
    reason_text = case.fact("denial.reason_text")
    reason_code = case.fact("denial.reason_code")

    if _unusable(reason_text) and _unusable(reason_code):
        return Classification(
            selected=None,
            candidates=(),
            ambiguous=False,
            explanation=(
                "The denial reason has not been established. Neither a reason code nor "
                "reason text was extracted, so there is nothing to classify against."
            ),
            blocked_by=("denial.reason_text", "denial.reason_code"),
        )

    candidates = _score_all(case, registry)

    if not candidates:
        return Classification(
            selected=None,
            candidates=(),
            ambiguous=False,
            explanation=(
                "The denial reason was read, but it does not match any rule pack "
                "currently installed. The category is outside what this system covers, "
                "which is a limit worth surfacing rather than forcing a fit."
            ),
        )

    top = candidates[0]

    if len(candidates) > 1:
        runner_up = candidates[1]
        if top.score - runner_up.score < AMBIGUITY_MARGIN:
            return Classification(
                selected=None,
                candidates=tuple(candidates),
                ambiguous=True,
                explanation=(
                    "The notice supports more than one denial category: "
                    f"{top.pack.display_name} and {runner_up.pack.display_name} score "
                    f"{top.score:.2f} and {runner_up.score:.2f}. Appealing against the "
                    "wrong reason is a common way these files are lost, so the choice is "
                    "left to a person."
                ),
            )

    return Classification(
        selected=top.pack,
        candidates=tuple(candidates),
        ambiguous=False,
        explanation=f"Matched {top.pack.display_name}: " + "; ".join(
            s.describe() for s in top.signals
        ),
    )


def _score_all(case: Case, registry: PackRegistry) -> list[PackCandidate]:
    candidates: list[PackCandidate] = []
    for pack in registry:
        signals = _signals_for(case, pack)
        if signals:
            base = max(s.weight for s in signals)
            bonus = CORROBORATION_BONUS * (len(signals) - 1)
            candidates.append(
                PackCandidate(pack=pack, score=min(1.0, base + bonus), signals=tuple(signals))
            )
    candidates.sort(key=lambda c: (-c.score, c.pack.id))
    return candidates


def _signals_for(case: Case, pack: RulePack) -> list[MatchSignal]:
    threshold = pack.match.min_confidence
    signals: list[MatchSignal] = []

    for rule in pack.match.any_of:
        if rule.reason_code_in:
            fact = case.fact("denial.reason_code")
            if _usable(fact, threshold) and isinstance(fact.value, str):
                code = fact.value.strip().upper()
                if any(code == expected.strip().upper() for expected in rule.reason_code_in):
                    signals.append(
                        MatchSignal(
                            kind="reason_code",
                            detail=f"reason code {fact.value}",
                            source_field="denial.reason_code",
                            weight=REASON_CODE_WEIGHT,
                            doc_id=fact.provenance.doc_id if fact.provenance else None,
                            page=fact.provenance.page if fact.provenance else None,
                        )
                    )

        if rule.phrase_matches:
            fact = case.fact(rule.phrase_field)
            if _usable(fact, threshold) and isinstance(fact.value, str):
                haystack = " ".join(fact.value.split()).casefold()
                for phrase in rule.phrase_matches:
                    needle = " ".join(phrase.split()).casefold()
                    if needle and needle in haystack:
                        signals.append(
                            MatchSignal(
                                kind="phrase",
                                detail=f'phrase "{phrase}"',
                                source_field=rule.phrase_field,
                                weight=PHRASE_WEIGHT,
                                doc_id=fact.provenance.doc_id if fact.provenance else None,
                                page=fact.provenance.page if fact.provenance else None,
                            )
                        )

    return signals


def _usable(fact: Fact | None, threshold: float) -> bool:
    """Whether a fact may be matched against.

    A fact below the pack's confidence threshold is treated as not present. Classification
    is a branch point for everything downstream, so it declines to build on a weak reading.
    """
    if fact is None or not fact.is_known or fact.value is None:
        return False
    if fact.confidence is not None and fact.confidence < threshold:
        return False
    return True


def _unusable(fact: Fact | None) -> bool:
    return fact is None or not fact.is_known or fact.value is None
