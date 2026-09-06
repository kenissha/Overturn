"""Normalised document text, and the span arithmetic the interface depends on.

A character span is only useful if two things agree on what the text is. Extraction reads
this normalised text, the interface highlights this normalised text, and the ledger's
provenance check verifies against this normalised text. Normalisation happens once, here.

Spans are **page-local**: ``(page, char_span)`` means "characters ``start:end`` of the
normalised text of that page". Page-local spans survive re-ingesting a single page and map
directly onto what the reader is looking at.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

# Characters that carry no visible meaning but can hide instructions from a human reader
# while remaining perfectly readable to a model. Stripping them is both normalisation and
# a defence: see docs/security-model.md.
_INVISIBLE = re.compile(
    "["
    "​-‏"  # zero-width space through right-to-left mark
    "‪-‮"  # bidirectional overrides
    "⁠-⁤"  # word joiner, invisible operators
    "﻿"  # byte order mark
    "­"  # soft hyphen
    "]"
)

_WHITESPACE = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def normalise(text: str) -> str:
    """Canonical text form. Every span in the system indexes into the output of this.

    Deliberately conservative: it collapses runs of spaces and strips invisible
    characters, but never reflows lines or removes punctuation. Aggressive normalisation
    would make spans easier to match and quotes harder to trust.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _INVISIBLE.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def count_invisible(text: str) -> int:
    """How many invisible characters normalisation removed.

    A denial letter has no legitimate reason to contain them. A non-zero count on an
    incoming document is an anomaly signal, not a formatting quirk.
    """
    return len(_INVISIBLE.findall(unicodedata.normalize("NFC", text)))


@dataclass(frozen=True, slots=True)
class DocumentText:
    """The normalised text of one document, page by page."""

    doc_id: str
    pages: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_pages(cls, doc_id: str, pages: list[str]) -> DocumentText:
        return cls(doc_id=doc_id, pages=tuple(normalise(p) for p in pages))

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def page_text(self, page: int) -> str:
        """Text of a 1-indexed page."""
        if page < 1 or page > len(self.pages):
            raise IndexError(f"{self.doc_id}: page {page} out of range (1..{len(self.pages)})")
        return self.pages[page - 1]

    def slice(self, page: int, span: tuple[int, int]) -> str:
        """The exact text a provenance record points at."""
        text = self.page_text(page)
        start, end = span
        if start < 0 or end > len(text) or end <= start:
            raise IndexError(
                f"{self.doc_id} page {page}: span {span} outside text of length {len(text)}"
            )
        return text[start:end]

    def find(self, page: int, needle: str) -> tuple[int, int] | None:
        """Locate ``needle`` on a page, returning its span. Used by corpus tooling."""
        text = self.page_text(page)
        idx = text.find(needle)
        return None if idx < 0 else (idx, idx + len(needle))

    def sha256(self) -> str:
        digest = hashlib.sha256()
        for page in self.pages:
            digest.update(page.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()


def quotes_match(actual: str, claimed: str) -> bool:
    """Whether a claimed quote matches the text actually at the span.

    Tolerant of whitespace only. A model that paraphrases what it 'saw' is a model whose
    provenance cannot be trusted for highlighting, so anything beyond whitespace drift is
    treated as a mismatch.
    """
    return " ".join(actual.split()).casefold() == " ".join(claimed.split()).casefold()
