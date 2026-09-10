"""The only tools an extraction agent is given.

This module is the security surface of the untrusted zone. An agent reading a document it
cannot trust holds exactly two capabilities, both defined here:

``write_fact``
    Record a value, with a source that is *verified against the document*, not merely
    supplied. Claiming a span is not enough; the text at that span must match the quote.

``mark_missing``
    State that the document does not establish a field. Abstention is a first-class
    action with its own tool, so that choosing not to answer is recorded, auditable and
    measurable rather than inferred from silence.

There is nothing else. No tool here can send, submit, notify, schedule, close a case or
compute a deadline. An instruction hidden in a document asking for any of those is read by
an agent that has no way to perform them.

Framework-agnostic on purpose: these are plain callables so the guarantees can be tested
without an agent SDK or a model provider installed. The Strands ``@tool`` wrappers live in
``overturn/agents/`` and add nothing but the decorator.
"""

from __future__ import annotations

from dataclasses import dataclass

from overturn.ledger.documents import DocumentText, quotes_match
from overturn.ledger.errors import (
    FieldNotWritableBy,
    LedgerError,
    ProvenanceRequired,
    UnknownField,
)
from overturn.ledger.fields import FieldOrigin, get_field
from overturn.ledger.schema import (
    Case,
    ConflictSource,
    Fact,
    FactStatus,
    FactValue,
    Provenance,
)
from overturn.ledger.store import CaseStore
from overturn.tools.quoting import coerce_value, locate_quote


class ProvenanceNotVerified(LedgerError):
    """The claimed source does not contain the claimed text.

    Distinct from :class:`ProvenanceRequired`: a source was given, but checking it against
    the document showed it was not where the model said it was. A fact is only as good as
    a citation that survives being followed.
    """


class SettledByPerson(LedgerError):
    """A person has confirmed or stated this field. A document does not overwrite that."""


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What the agent is told, and what the audit log records."""

    ok: bool
    field: str
    message: str
    error_type: str | None = None

    def __str__(self) -> str:
        return self.message


class LedgerWriter:
    """Binds the write tools to one case, one actor and that case's document text.

    The agent never chooses which case it writes to and never supplies the document text
    its citations are checked against. Both are fixed by the caller that constructed this
    writer, outside the agent's reach.
    """

    def __init__(
        self,
        store: CaseStore,
        case: Case,
        *,
        actor: str,
        texts: dict[str, DocumentText],
        allowed_origins: frozenset[FieldOrigin] = frozenset({FieldOrigin.DOCUMENT}),
    ) -> None:
        self.store = store
        self.case = case
        self.actor = actor
        self.texts = texts
        self.allowed_origins = allowed_origins

    # -- tools --------------------------------------------------------------------

    def write_fact(
        self,
        field: str,
        value: FactValue,
        doc_id: str,
        page: int,
        char_span_start: int,
        char_span_end: int,
        quote: str,
        confidence: float,
    ) -> WriteResult:
        """Record a fact you can point at in the document.

        Every argument is required. If you cannot give the document, page, character span
        and the exact quoted text, you must call ``mark_missing`` instead. The quote is
        checked against the document: if the text at that span is not what you quoted, the
        write is refused.

        Args:
            field: A field name from the fact taxonomy.
            value: The value read from the document.
            doc_id: The document the value was read from.
            page: 1-indexed page number.
            char_span_start: Start offset of the quote within that page's normalised text.
            char_span_end: End offset, exclusive.
            quote: The exact text at that span, copied verbatim.
            confidence: How confident you are, from 0.0 to 1.0.
        """
        try:
            fact = self._build_fact(
                field=field,
                value=value,
                doc_id=doc_id,
                page=page,
                span=(char_span_start, char_span_end),
                quote=quote,
                confidence=confidence,
            )
            fact = _reconcile(self.case.fact(field), fact, self.actor)
            self.store.put_fact(self.case, fact)
        except LedgerError as exc:
            return self._refuse(field, exc, value=value)
        except (ValueError, IndexError) as exc:
            return self._refuse(field, exc, value=value)

        self.store.save(self.case)
        self.store.record_write(
            self.case.case_id,
            actor=self.actor,
            field=field,
            outcome="accepted",
            detail=f"{doc_id} p{page} [{char_span_start}:{char_span_end}]"
            + (
                " (conflicts with another document)" if fact.status is FactStatus.CONFLICTED else ""
            ),
            value=value,
        )
        if fact.status is FactStatus.CONFLICTED:
            return WriteResult(
                True,
                field,
                f"Recorded {field} as conflicted: another document on this case states a "
                "different value. A person decides which reading stands.",
            )
        return WriteResult(True, field, f"Recorded {field} with source {doc_id} page {page}.")

    def mark_missing(self, field: str, reason: str) -> WriteResult:
        """Record that this document does not establish a field.

        Use this whenever you cannot cite a source. It is a correct answer, not a failure:
        a recorded gap is more useful to an advocate than a plausible guess.

        Args:
            field: A field name from the fact taxonomy.
            reason: Why it is absent, in a few words. Shown to the human beside the gap.
        """
        try:
            self._check_writable(field)
            if not reason or not reason.strip():
                raise ValueError("mark_missing requires a reason")
            existing = self.case.fact(field)
            if existing is not None and (
                existing.is_known or existing.status is FactStatus.CONFLICTED
            ):
                # One document being silent does not erase what another states.
                self.store.record_write(
                    self.case.case_id,
                    actor=self.actor,
                    field=field,
                    outcome="accepted",
                    detail=f"not stated here; kept the value already recorded ({reason})",
                )
                return WriteResult(
                    True,
                    field,
                    f"{field} is not stated in this document; the value already recorded "
                    "from another source was kept.",
                )
            fact = Fact(
                field=field,
                value=None,
                status=FactStatus.MISSING,
                reason=reason.strip(),
                recorded_by=self.actor,
            )
            self.store.put_fact(self.case, fact)
        except LedgerError as exc:
            return self._refuse(field, exc)
        except ValueError as exc:
            return self._refuse(field, exc)

        self.store.save(self.case)
        self.store.record_write(
            self.case.case_id,
            actor=self.actor,
            field=field,
            outcome="accepted",
            detail=f"missing: {reason}",
        )
        return WriteResult(True, field, f"Recorded {field} as missing.")

    def write_fact_by_quote(
        self,
        field: str,
        value: FactValue,
        doc_id: str,
        page: int,
        quote: str,
        confidence: float,
    ) -> WriteResult:
        """Record a fact by quoting it. The span is found by this tool, not claimed.

        This is the form the extraction agent is given. Models copy text far more reliably
        than they count characters, so the agent supplies the quote and the page, and the
        quote is located on that page here. The guarantee is unchanged: a quote that is
        not on the page is not found, and nothing is written.

        String values are converted to the field's type by code (see
        :mod:`overturn.tools.quoting`), so "August 1, 2026" becomes ``2026-08-01`` without
        asking a model to do date handling.
        """
        try:
            self._check_writable(field)
            parsed = coerce_value(field, value)
            if not quote or not quote.strip():
                raise ProvenanceRequired(
                    "A quote is required: copy the text that states the value exactly as it "
                    "is printed, or call mark_missing."
                )
            text = self.texts.get(doc_id)
            if text is None:
                raise ProvenanceRequired(
                    f"No document text available for {doc_id!r}. A value can only be "
                    "recorded against a document this case actually holds."
                )
            span = locate_quote(text.page_text(page), quote)
            if span is None:
                raise ProvenanceNotVerified(
                    f"The quote {quote!r} does not appear on {doc_id} page {page}. Copy the "
                    "text exactly as printed, check the page number, or call mark_missing."
                )
        except LedgerError as exc:
            return self._refuse(field, exc, value=value)
        except (ValueError, IndexError) as exc:
            return self._refuse(field, exc, value=value)

        return self.write_fact(
            field=field,
            value=parsed,
            doc_id=doc_id,
            page=page,
            char_span_start=span[0],
            char_span_end=span[1],
            # Record what is actually on the page, not the model's copy of it: the quote
            # was located tolerantly, and provenance should hold the text a reader will see.
            quote=text.page_text(page)[span[0] : span[1]],
            confidence=confidence,
        )

    # -- internals ----------------------------------------------------------------

    def _build_fact(
        self,
        *,
        field: str,
        value: FactValue,
        doc_id: str,
        page: int,
        span: tuple[int, int],
        quote: str,
        confidence: float,
    ) -> Fact:
        self._check_writable(field)

        if value is None:
            raise ProvenanceRequired(
                f"{field}: write_fact cannot record an absent value. Call mark_missing "
                "with a reason instead."
            )

        verified_quote = self._verify_provenance(doc_id, page, span, quote)

        return Fact(
            field=field,
            value=value,
            status=FactStatus.EXTRACTED,
            confidence=confidence,
            provenance=Provenance(
                doc_id=doc_id,
                page=page,
                char_span=span,
                quote=verified_quote,
            ),
            recorded_by=self.actor,
        )

    def _check_writable(self, field: str) -> None:
        spec = get_field(field)
        if spec is None:
            raise UnknownField(
                f"{field!r} is not a field in the fact taxonomy. Only declared fields can "
                "be recorded."
            )
        if spec.origin not in self.allowed_origins:
            raise FieldNotWritableBy(
                f"{field!r} has origin {spec.origin.value!r} and cannot be written by "
                f"{self.actor}. " + _ORIGIN_EXPLANATION.get(spec.origin, "")
            )

    def _verify_provenance(self, doc_id: str, page: int, span: tuple[int, int], quote: str) -> str:
        """Follow the citation. A source that cannot be followed is not a source."""
        text = self.texts.get(doc_id)
        if text is None:
            raise ProvenanceRequired(
                f"No document text available for {doc_id!r}. A value can only be recorded "
                "against a document this case actually holds."
            )
        actual = text.slice(page, span)  # raises IndexError on an out-of-range span
        if not quote or not quote.strip():
            raise ProvenanceRequired(
                "A quote is required: it is what the interface highlights and what makes "
                "the citation checkable."
            )
        if not quotes_match(actual, quote):
            raise ProvenanceNotVerified(
                f"Quote does not match the document. At {doc_id} page {page} "
                f"[{span[0]}:{span[1]}] the text reads {actual!r}, but {quote!r} was "
                "claimed. Re-read the document and cite the exact span."
            )
        return actual

    def _refuse(self, field: str, exc: Exception, value: FactValue = None) -> WriteResult:
        error_type = type(exc).__name__
        self.store.record_write(
            self.case.case_id,
            actor=self.actor,
            field=field,
            outcome="refused",
            error_type=error_type,
            detail=str(exc),
            value=value,
        )
        return WriteResult(False, field, f"Refused: {exc}", error_type=error_type)


_PERSON_STATUSES = (FactStatus.HUMAN_VERIFIED, FactStatus.HUMAN_ANSWERED)


def _reconcile(existing: Fact | None, new: Fact, actor: str) -> Fact:
    """What to record when a field already has a value.

    Re-reading the same document replaces its own reading. A different document that
    agrees replaces it too. A different document that disagrees does not win and does not
    lose: both readings are kept, side by side, as a conflict for a person to decide —
    often the strongest argument in the file. And nothing a document says overwrites
    what a person has confirmed or stated.
    """
    if existing is None or new.provenance is None:
        return new
    if existing.status is FactStatus.CONFLICTED:
        return _conflict(list(existing.conflict), new, actor)
    if existing.status in _PERSON_STATUSES:
        other_document = (
            existing.provenance is not None and existing.provenance.doc_id != new.provenance.doc_id
        )
        if other_document and existing.value != new.value:
            side = ConflictSource(reads=existing.value, provenance=existing.provenance)
            return _conflict([side], new, actor)
        raise SettledByPerson(
            f"{new.field} was settled by {existing.verified_by}; a document does not "
            "overwrite a person's answer. Nothing was changed."
        )
    if existing.status is not FactStatus.EXTRACTED or existing.provenance is None:
        return new
    if existing.provenance.doc_id == new.provenance.doc_id or existing.value == new.value:
        return new
    side = ConflictSource(reads=existing.value, provenance=existing.provenance)
    return _conflict([side], new, actor)


def _conflict(sides: list[ConflictSource], new: Fact, actor: str) -> Fact:
    incoming = ConflictSource(reads=new.value, provenance=new.provenance)
    if incoming not in sides:
        sides.append(incoming)
    return Fact(
        field=new.field,
        value=None,
        status=FactStatus.CONFLICTED,
        conflict=sides,
        recorded_by=actor,
    )


_ORIGIN_EXPLANATION = {
    FieldOrigin.ENGINE: (
        "Deadlines are computed by the deterministic engine and are never written from a document."
    ),
    FieldOrigin.HUMAN: (
        "This is a judgment no document settles. It is raised with a person instead of "
        "being inferred."
    ),
}
