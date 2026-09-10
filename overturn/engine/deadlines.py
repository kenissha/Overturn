"""Deadline arithmetic.

No model touches this module. Every date it produces is a pure function of facts already
in the ledger, which is why it can be exhaustively unit tested and why a wrong answer here
is a bug rather than a sampling artefact.

Three rules govern everything below.

**A date stated in the letter wins.** Federal timeframes are a floor. States extend them,
plans grant longer windows, and other lines of coverage run different regimes entirely. If
the notice states a deadline, that is the deadline; the statutory default is only a
fallback, and when used it is marked ``regime_default`` so the interface never implies the
letter said something it did not.

**The clock runs from receipt, not from the notice date.** The regulations start the
appeal window at receipt of the adverse benefit determination. When the receipt date is
unknown we fall back to the notice date, which is on or before receipt and therefore
yields an *earlier* deadline. Erring toward less time is the only safe direction: a system
that overestimates the window causes exactly the failure it exists to prevent.

**Compute what is knowable, block what is not.** A missing fact blocks the deadlines that
depend on it and nothing else. The filing window is 180 days in every internal regime, so
it can be computed before anyone knows whether the claim was pre- or post-service; only
the plan's response window has to wait.

Sources for every figure are recorded in docs/sources.md.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum

from overturn.ledger.schema import Case

# --- regimes -----------------------------------------------------------------------


class Regime(StrEnum):
    """Which set of statutory timeframes applies."""

    ACA_INTERNAL_PRE_SERVICE = "aca_internal_pre_service"
    ACA_INTERNAL_POST_SERVICE = "aca_internal_post_service"
    ACA_URGENT = "aca_urgent"
    ACA_EXTERNAL = "aca_external"


@dataclass(frozen=True, slots=True)
class RegimeSpec:
    file_within_days: int | None = None
    file_within_months: int | None = None
    plan_responds_within_days: int | None = None
    plan_responds_within_hours: int | None = None
    description: str = ""


REGIMES: dict[Regime, RegimeSpec] = {
    Regime.ACA_INTERNAL_POST_SERVICE: RegimeSpec(
        file_within_days=180,
        plan_responds_within_days=60,
        description="ACA internal appeal, post-service claim",
    ),
    Regime.ACA_INTERNAL_PRE_SERVICE: RegimeSpec(
        file_within_days=180,
        plan_responds_within_days=30,
        description="ACA internal appeal, pre-service claim",
    ),
    Regime.ACA_URGENT: RegimeSpec(
        file_within_days=180,
        plan_responds_within_hours=72,
        description="ACA internal appeal, urgent care claim",
    ),
    Regime.ACA_EXTERNAL: RegimeSpec(
        file_within_months=4,
        plan_responds_within_days=45,
        description="ACA external review after a final adverse determination",
    ),
}

FILING_DEADLINES = frozenset({"deadline.internal_appeal_due", "deadline.external_review_due"})
"""Windows the advocate files within. Once a filing is recorded they are met."""

INTERNAL_FILING_DAYS = 180
"""Identical across every internal regime, which is why the filing deadline can be
computed without knowing whether the claim was pre- or post-service."""


# --- results ------------------------------------------------------------------------


class Basis(StrEnum):
    """Where a computed date came from."""

    STATED_IN_LETTER = "stated_in_letter"
    """Read from the notice. Beats any default."""

    REGIME_DEFAULT = "regime_default"
    """Derived from the statutory fallback because the notice stated nothing."""


class Pressure(StrEnum):
    """How close a deadline is, in the bands the escalation gate acts on."""

    NONE = "none"
    INFO = "info"  # T-30: visible, not notified
    ELEVATED = "elevated"  # T-14: escalation
    URGENT = "urgent"  # T-7
    CRITICAL = "critical"  # T-3
    EXPIRED = "expired"  # T-0 and past

    @property
    def escalates(self) -> bool:
        """Whether crossing into this band raises escalation trigger 3."""
        return self in (Pressure.ELEVATED, Pressure.URGENT, Pressure.CRITICAL, Pressure.EXPIRED)


PRESSURE_TIERS: tuple[tuple[int, Pressure], ...] = (
    (3, Pressure.CRITICAL),
    (7, Pressure.URGENT),
    (14, Pressure.ELEVATED),
    (30, Pressure.INFO),
)


@dataclass(frozen=True, slots=True)
class ComputedDeadline:
    field: str
    due: date
    basis: Basis
    regime: Regime | None
    anchor_field: str
    anchor_date: date
    anchor_is_estimated: bool
    rule: str
    met_on: date | None = None
    """Set once a person records the filing. A met window is no longer pressing."""

    def days_remaining(self, today: date) -> int:
        return (self.due - today).days

    def pressure(self, today: date) -> Pressure:
        if self.met_on is not None:
            return Pressure.NONE
        remaining = self.days_remaining(today)
        if remaining < 0:
            return Pressure.EXPIRED
        for threshold, level in PRESSURE_TIERS:
            if remaining <= threshold:
                return level
        return Pressure.NONE


@dataclass(frozen=True, slots=True)
class BlockedDeadline:
    """A deadline that could not be computed, and precisely what is missing.

    Blocked is not the same as absent. The advocate is told which fact would unblock it,
    which is what turns a gap into a next action.
    """

    field: str
    missing_fields: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class DeadlineComputation:
    deadlines: tuple[ComputedDeadline, ...]
    blocked: tuple[BlockedDeadline, ...]
    regime: Regime | None
    regime_blocked_by: tuple[str, ...] = ()

    def get(self, field: str) -> ComputedDeadline | None:
        return next((d for d in self.deadlines if d.field == field), None)

    def highest_pressure(self, today: date) -> Pressure:
        levels = [d.pressure(today) for d in self.deadlines]
        if not levels:
            return Pressure.NONE
        order = list(Pressure)
        return max(levels, key=order.index)


# --- regime selection ---------------------------------------------------------------


def select_regime(case: Case) -> tuple[Regime | None, tuple[str, ...]]:
    """Choose the applicable regime, or report exactly what is missing.

    Order matters. A final adverse determination moves the case to external review
    regardless of how the underlying claim was classified. Urgency then overrides the
    pre/post-service split, because an urgent claim compresses the plan's response window
    to hours whether or not the service has been rendered.
    """
    if case.value("denial.is_final") is True:
        return Regime.ACA_EXTERNAL, ()

    if case.value("service.was_urgent") is True:
        return Regime.ACA_URGENT, ()

    is_pre = case.value("service.is_pre_service")
    if is_pre is True:
        return Regime.ACA_INTERNAL_PRE_SERVICE, ()
    if is_pre is False:
        return Regime.ACA_INTERNAL_POST_SERVICE, ()

    missing = ("service.is_pre_service",)
    if case.value("service.was_urgent") is None:
        missing = ("service.is_pre_service", "service.was_urgent")
    return None, missing


# --- the anchor ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Anchor:
    field: str
    on: date
    estimated: bool
    note: str


def appeal_clock_anchor(case: Case) -> Anchor | None:
    """The date the appeal window starts running from.

    Prefers the recorded receipt date. Falls back to the notice date, which is on or
    before receipt, so the fallback can only shorten the computed window. It is flagged as
    estimated so the interface can say so and the advocate can correct it.
    """
    received = _as_date(case.value("denial.received_date"))
    if received is not None:
        return Anchor(
            field="denial.received_date",
            on=received,
            estimated=False,
            note="date the notice was received",
        )

    notice = _as_date(case.value("denial.notice_date"))
    if notice is not None:
        return Anchor(
            field="denial.notice_date",
            on=notice,
            estimated=True,
            note=(
                "receipt date unknown; the notice date is used because it is on or before "
                "receipt and therefore yields the earlier, safer deadline"
            ),
        )
    return None


# --- the computation ----------------------------------------------------------------


def compute_deadlines(case: Case) -> DeadlineComputation:
    """Compute every deadline the ledger supports, and report the rest as blocked."""
    deadlines: list[ComputedDeadline] = []
    blocked: list[BlockedDeadline] = []

    regime, regime_missing = select_regime(case)
    anchor = appeal_clock_anchor(case)

    if anchor is None:
        missing = ("denial.received_date", "denial.notice_date")
        return DeadlineComputation(
            deadlines=(),
            blocked=(
                BlockedDeadline(
                    field="deadline.internal_appeal_due",
                    missing_fields=missing,
                    explanation=(
                        "No date starts the appeal clock. Neither the notice date nor the "
                        "receipt date was found, so no filing window can be computed. "
                        "This is surfaced rather than guessed."
                    ),
                ),
                BlockedDeadline(
                    field="deadline.plan_response_due",
                    missing_fields=missing,
                    explanation="Depends on the filing deadline, which cannot be computed.",
                ),
            ),
            regime=regime,
            regime_blocked_by=regime_missing,
        )

    is_external = regime is Regime.ACA_EXTERNAL

    # --- filing deadline -------------------------------------------------------
    stated = _as_date(case.value("denial.stated_appeal_deadline"))
    filing_field = "deadline.external_review_due" if is_external else "deadline.internal_appeal_due"

    if stated is not None:
        deadlines.append(
            ComputedDeadline(
                field=filing_field,
                due=stated,
                basis=Basis.STATED_IN_LETTER,
                regime=regime,
                anchor_field="denial.stated_appeal_deadline",
                anchor_date=stated,
                anchor_is_estimated=False,
                rule="deadline printed in the notice; a stated date overrides the "
                "statutory default",
            )
        )
    elif is_external:
        deadlines.append(
            ComputedDeadline(
                field="deadline.external_review_due",
                due=add_months(anchor.on, 4),
                basis=Basis.REGIME_DEFAULT,
                regime=Regime.ACA_EXTERNAL,
                anchor_field=anchor.field,
                anchor_date=anchor.on,
                anchor_is_estimated=anchor.estimated,
                rule="4 months from receipt of the final adverse determination",
            )
        )
    else:
        deadlines.append(
            ComputedDeadline(
                field="deadline.internal_appeal_due",
                due=anchor.on + timedelta(days=INTERNAL_FILING_DAYS),
                basis=Basis.REGIME_DEFAULT,
                regime=regime,
                anchor_field=anchor.field,
                anchor_date=anchor.on,
                anchor_is_estimated=anchor.estimated,
                rule=f"{INTERNAL_FILING_DAYS} days from receipt of the adverse benefit "
                "determination",
            )
        )

    # --- the plan's response window --------------------------------------------
    if regime is None:
        blocked.append(
            BlockedDeadline(
                field="deadline.plan_response_due",
                missing_fields=regime_missing,
                explanation=(
                    "The plan's response window depends on how the claim is classified: "
                    "30 days pre-service, 60 days post-service, 72 hours if urgent. The "
                    "filing deadline is unaffected and has been computed."
                ),
            )
        )
    else:
        spec = REGIMES[regime]
        if spec.plan_responds_within_days is not None:
            filed = _as_date(case.value("appeal.filed_date"))
            if filed is None:
                blocked.append(
                    BlockedDeadline(
                        field="deadline.plan_response_due",
                        missing_fields=("appeal.filed_date",),
                        explanation=(
                            f"The plan has {spec.plan_responds_within_days} days to "
                            "respond once the appeal is filed. The clock starts on the "
                            "filing date, which has not been recorded yet."
                        ),
                    )
                )
            else:
                deadlines.append(
                    ComputedDeadline(
                        field="deadline.plan_response_due",
                        due=filed + timedelta(days=spec.plan_responds_within_days),
                        basis=Basis.REGIME_DEFAULT,
                        regime=regime,
                        anchor_field="appeal.filed_date",
                        anchor_date=filed,
                        anchor_is_estimated=False,
                        rule=f"{spec.plan_responds_within_days} days from filing "
                        f"({spec.description})",
                    )
                )
        else:
            blocked.append(
                BlockedDeadline(
                    field="deadline.plan_response_due",
                    missing_fields=("appeal.filed_date",),
                    explanation=(
                        f"An urgent claim is decided within {spec.plan_responds_within_hours} "
                        "hours of filing. That window is tracked in hours and is not a "
                        "calendar deadline."
                    ),
                )
            )

    filed = _as_date(case.value("appeal.filed_date"))
    if filed is not None:
        deadlines = [
            replace(d, met_on=filed) if d.field in FILING_DEADLINES else d for d in deadlines
        ]

    return DeadlineComputation(
        deadlines=tuple(deadlines),
        blocked=tuple(blocked),
        regime=regime,
        regime_blocked_by=regime_missing,
    )


# --- date helpers -------------------------------------------------------------------


def add_months(start: date, months: int) -> date:
    """Add calendar months, clamping to the end of the target month.

    Four months from 31 October is 28 or 29 February, not 2 or 3 March. Rolling past the
    end of the month would hand the advocate days they do not have.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _as_date(value: object) -> date | None:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, date):
        return value
    return None
