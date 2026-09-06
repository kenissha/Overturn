"""Ledger errors.

Every error in this module represents a write the ledger refused. They exist so that a
refusal is loud and traceable rather than a silently dropped field: if an agent tried to
record something it was not entitled to record, that attempt is itself signal.
"""


class LedgerError(Exception):
    """Base class for every ledger rejection."""


class UnknownField(LedgerError):
    """The field name is not in the taxonomy.

    Writing arbitrary field names is a ledger-pollution vector: an injected instruction
    could otherwise invent a field that downstream code happens to read.
    """


class FieldNotWritableBy(LedgerError):
    """The writer is not entitled to write this field.

    Deadlines are computed by the deterministic engine and can never be written by a
    model; human-judgment fields can only be answered by a person. This is enforced
    structurally rather than by instruction.
    """


class FactTypeMismatch(LedgerError):
    """The value does not match the type declared for the field in the taxonomy."""


class ProvenanceRequired(LedgerError):
    """A value was supplied without a usable source.

    This is the central invariant of the project: a fact with a value must be able to
    point at the document, page and character span it came from.
    """


class StatusInvariantViolation(LedgerError):
    """The combination of status, value and provenance is not a legal ledger state."""


class DocumentNotFound(LedgerError):
    """Provenance referenced a document that is not registered on the case."""
