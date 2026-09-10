"""The contract between the pipeline and whatever reads a document into the ledger.

An extractor receives one document's normalised text and the fields to handle, and records
facts exclusively through a :class:`LedgerWriter`. The production agent, the evaluation
calibrators and the tests all implement this same contract, which is why the numbers the
harness publishes describe the code path real cases take.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from overturn.tools.ledger_tools import LedgerWriter

DEFAULT_FIELDS: tuple[str, ...] = (
    "denial.notice_date",
    "denial.reason_text",
    "denial.reason_code",
    "denial.cited_policy_section",
    "denial.stated_appeal_deadline",
    "service.description",
    "service.cpt_codes",
    "service.date_of_service",
    "service.is_pre_service",
    "plan.issuer",
    "patient.member_id",
    "provider.name",
    "plan.covers_service",
)
"""The fields read from a denial letter. Every one is document-origin: deadlines and
judgment calls are never asked of an extractor."""

POLICY_FIELDS: tuple[str, ...] = (
    "plan.issuer",
    "plan.name",
    "plan.type",
    "plan.covers_service",
)
"""The fields read from a plan document: who issues it and what it says it covers."""

FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    "denial_letter": DEFAULT_FIELDS,
    "plan_document": POLICY_FIELDS,
}
"""Document kinds the extraction agent reads, and what it reads each for."""


@dataclass(frozen=True, slots=True)
class ExtractionInput:
    """Everything an extractor may see. Deliberately nothing more."""

    doc_id: str
    pages: tuple[str, ...]
    fields: tuple[str, ...]


Extractor = Callable[[ExtractionInput, LedgerWriter], None]
"""Reads the input and records facts exclusively through the writer's two tools."""
