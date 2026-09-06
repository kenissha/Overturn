"""Anomaly detection on incoming documents.

Deterministic and model-free, on purpose. Asking a model whether a document is trying to
manipulate a model puts the defence inside the thing being defended. These are pattern and
structure checks that run before any model sees the text, and they produce spans so the
interface can show the advocate exactly what was found and where.

**This is the second line, not the first.** The primary defence is that the agent reading
this text holds no outward-facing tools (see docs/security-model.md). Detection exists so
that a manipulation attempt becomes *visible* rather than merely ineffective: an advocate
should know that a document sent to them contained hidden instructions, because that says
something about the document.

Detection is not the security boundary. A pattern list can always be paraphrased around,
and nothing here is relied on to keep the system safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from overturn.ledger.documents import DocumentText, count_invisible


class AnomalyKind(StrEnum):
    INSTRUCTION_PATTERN = "instruction_pattern"
    """Text shaped like a directive to an automated reader."""

    HIDDEN_TEXT = "hidden_text"
    """Characters that render invisibly to a person but are read by a machine."""

    ROLE_IMPERSONATION = "role_impersonation"
    """Text imitating a system or assistant turn."""

    SUPPRESSION_REQUEST = "suppression_request"
    """Text asking that a human not be told something."""

    LOW_OCR_CONFIDENCE = "low_ocr_confidence"
    """The document was read poorly enough that extraction should not be trusted."""


class Severity(StrEnum):
    NOTE = "note"
    WARN = "warn"
    ALERT = "alert"


@dataclass(frozen=True, slots=True)
class Anomaly:
    kind: AnomalyKind
    severity: Severity
    doc_id: str
    page: int | None
    char_span: tuple[int, int] | None
    excerpt: str
    explanation: str

    @property
    def escalates(self) -> bool:
        """Whether this raises escalation trigger 4."""
        return self.severity in (Severity.WARN, Severity.ALERT)


# Patterns are deliberately narrow. A denial letter is a formal document; none of these
# phrasings have an innocent reading in one, which is what keeps false positives low
# enough that an alert still means something.
_PATTERNS: tuple[tuple[re.Pattern[str], AnomalyKind, Severity, str], ...] = (
    (
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b"
            r"(?:previous|prior|above|earlier|all)\b[^.\n]{0,20}\b"
            r"(?:instruction|prompt|direction|rule)s?\b",
            re.IGNORECASE,
        ),
        AnomalyKind.INSTRUCTION_PATTERN,
        Severity.ALERT,
        "Text instructing an automated reader to discard its instructions.",
    ),
    (
        re.compile(
            r"^\s*(?:system|assistant|user)\s*[:>]\s*\S",
            re.IGNORECASE | re.MULTILINE,
        ),
        AnomalyKind.ROLE_IMPERSONATION,
        Severity.ALERT,
        "A line formatted as a conversational turn, imitating system or assistant text.",
    ),
    (
        re.compile(
            r"\b(?:new|updated|revised)\s+(?:instruction|system\s+prompt|direction)s?\b",
            re.IGNORECASE,
        ),
        AnomalyKind.INSTRUCTION_PATTERN,
        Severity.ALERT,
        "Text presenting itself as a replacement set of instructions.",
    ),
    (
        re.compile(
            r"\byou\s+are\s+(?:now\s+)?(?:a|an|the)\s+\w+",
            re.IGNORECASE,
        ),
        AnomalyKind.ROLE_IMPERSONATION,
        Severity.WARN,
        "Text attempting to assign a role to an automated reader.",
    ),
    (
        re.compile(
            r"\bdo\s+not\b[^.\n]{0,30}\b(?:notify|inform|tell|alert|escalate|mention)\b",
            re.IGNORECASE,
        ),
        AnomalyKind.SUPPRESSION_REQUEST,
        Severity.ALERT,
        "Text asking that a person not be told something. Escalation is not suppressible.",
    ),
    (
        re.compile(
            r"\bwithout\s+(?:informing|notifying|telling|alerting)\b",
            re.IGNORECASE,
        ),
        AnomalyKind.SUPPRESSION_REQUEST,
        Severity.ALERT,
        "Text asking that an action be taken without informing a person.",
    ),
    (
        re.compile(
            r"\b(?:withdraw|cancel|close|drop|abandon|resolve)\b[^.\n]{0,25}\b"
            r"(?:claim|appeal|case|file|dispute)\b",
            re.IGNORECASE,
        ),
        AnomalyKind.INSTRUCTION_PATTERN,
        Severity.WARN,
        "Text directing that the claim or appeal be abandoned. No agent holds that power, "
        "but the request itself is worth seeing.",
    ),
)

OCR_CONFIDENCE_FLOOR = 0.80
"""Below this, extraction is reading a guess. The advocate is told rather than the
uncertainty being absorbed silently."""


def scan_text(doc_id: str, text: DocumentText) -> list[Anomaly]:
    """Scan a document's normalised text, page by page."""
    found: list[Anomaly] = []
    for page_number, page in enumerate(text.pages, start=1):
        for pattern, kind, severity, explanation in _PATTERNS:
            for match in pattern.finditer(page):
                found.append(
                    Anomaly(
                        kind=kind,
                        severity=severity,
                        doc_id=doc_id,
                        page=page_number,
                        char_span=match.span(),
                        excerpt=_excerpt(page, match.span()),
                        explanation=explanation,
                    )
                )
    return found


def scan_raw(doc_id: str, raw_pages: list[str]) -> list[Anomaly]:
    """Check the text *before* normalisation, for what normalisation removes.

    Zero-width and bidirectional characters are stripped during normalisation, so by the
    time extraction reads a page they are gone. They still happened, and a denial letter
    has no legitimate reason to contain them.
    """
    found: list[Anomaly] = []
    for page_number, raw in enumerate(raw_pages, start=1):
        hidden = count_invisible(raw)
        if hidden:
            found.append(
                Anomaly(
                    kind=AnomalyKind.HIDDEN_TEXT,
                    severity=Severity.ALERT if hidden > 3 else Severity.WARN,
                    doc_id=doc_id,
                    page=page_number,
                    char_span=None,
                    excerpt=f"{hidden} invisible character(s)",
                    explanation=(
                        "Characters that render invisibly to a reader but are read by a "
                        "machine. They were removed before extraction; their presence is "
                        "reported because a formal notice has no reason to contain them."
                    ),
                )
            )
    return found


def check_ocr_confidence(doc_id: str, confidence: float | None) -> list[Anomaly]:
    if confidence is None or confidence >= OCR_CONFIDENCE_FLOOR:
        return []
    return [
        Anomaly(
            kind=AnomalyKind.LOW_OCR_CONFIDENCE,
            severity=Severity.WARN,
            doc_id=doc_id,
            page=None,
            char_span=None,
            excerpt=f"OCR confidence {confidence:.2f}",
            explanation=(
                f"Below the {OCR_CONFIDENCE_FLOOR:.2f} floor. Facts extracted from this "
                "document should be confirmed against the original before the packet goes "
                "out."
            ),
        )
    ]


def scan_document(
    doc_id: str,
    raw_pages: list[str],
    *,
    ocr_confidence: float | None = None,
) -> list[Anomaly]:
    """Every check, in the order they apply to an incoming document."""
    normalised = DocumentText.from_pages(doc_id, raw_pages)
    return [
        *scan_raw(doc_id, raw_pages),
        *scan_text(doc_id, normalised),
        *check_ocr_confidence(doc_id, ocr_confidence),
    ]


def _excerpt(page: str, span: tuple[int, int], context: int = 40) -> str:
    start = max(0, span[0] - context)
    end = min(len(page), span[1] + context)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(page) else ""
    return prefix + " ".join(page[start:end].split()) + suffix
