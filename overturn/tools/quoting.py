"""Turning what a model says into what the ledger accepts — deterministically.

Two conversions happen between the extraction agent and the ledger, and both are done by
code rather than by asking the model to be precise:

**Quotes become spans.** Models are unreliable at counting characters and reliable at
copying text. So the agent quotes, and :func:`locate_quote` finds that quote on the page.
The guarantee does not weaken: a quote that is not on the page is not found, and nothing
is written. Whitespace and letter case are tolerated because line breaks and capitalisation
are the parts of copying models get wrong without meaning anything by it.

**Strings become typed values.** A date printed as "August 1, 2026" is converted to
``2026-08-01`` here, by a parser, rather than by the model. Date arithmetic is exactly the
kind of thing this project refuses to delegate to a model, and date *parsing* is its first
step.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from overturn.ledger.errors import FactTypeMismatch, UnknownField
from overturn.ledger.fields import FactKind, get_field
from overturn.ledger.schema import FactValue

_WRAPPING = "\"'“”‘’`"

_MONTHS: dict[str, int] = {}
for _i in range(1, 13):
    _MONTHS[calendar.month_name[_i].lower()] = _i
    _MONTHS[calendar.month_abbr[_i].lower()] = _i
_MONTHS["sept"] = 9

_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


def locate_quote(page_text: str, quote: str) -> tuple[int, int] | None:
    """Find a quote on a page, tolerating whitespace and case. ``None`` if absent."""
    for candidate in (quote, quote.strip().strip(_WRAPPING)):
        tokens = candidate.split()
        if not tokens:
            continue
        pattern = r"\s+".join(re.escape(token) for token in tokens)
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            return match.span()
    return None


def coerce_value(field_name: str, raw: FactValue) -> FactValue:
    """Convert an agent-supplied string into the field's declared type.

    Non-string values pass through untouched; the ledger's own validation still applies
    to them. Anything that cannot be converted raises :class:`FactTypeMismatch`, which the
    writer turns into a refusal the agent can read and act on.
    """
    spec = get_field(field_name)
    if spec is None:
        raise UnknownField(f"{field_name!r} is not a field in the fact taxonomy.")
    if not isinstance(raw, str):
        return raw

    text = raw.strip()
    kind = spec.kind

    if kind is FactKind.STRING:
        return text

    if kind is FactKind.BOOL:
        lowered = text.lower().rstrip(".")
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise FactTypeMismatch(f"{field_name}: expected true or false, got {raw!r}")

    if kind is FactKind.INT:
        try:
            return int(text)
        except ValueError as exc:
            raise FactTypeMismatch(f"{field_name}: expected a whole number, got {raw!r}") from exc

    if kind is FactKind.STRING_LIST:
        items = [item.strip() for item in re.split(r"[,;]", text) if item.strip()]
        if not items:
            raise FactTypeMismatch(f"{field_name}: expected a comma-separated list")
        return items

    if kind is FactKind.DATE:
        return parse_date(field_name, text)

    return text


def parse_date(field_name: str, text: str) -> str:
    """Parse the date formats US denial notices actually print, into ISO-8601.

    Slash dates are read month-first, as US correspondence writes them. A date that does
    not exist on the calendar is refused rather than rolled over.
    """
    s = text.strip().rstrip(".").replace(",", ", ").replace("  ", " ")
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        pass

    try:
        if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s):
            return date(int(m[3]), int(m[1]), int(m[2])).isoformat()
        if m := re.fullmatch(r"([A-Za-z]+)\.? (\d{1,2}), ?(\d{4})", s):
            if m[1].lower() in _MONTHS:
                return date(int(m[3]), _MONTHS[m[1].lower()], int(m[2])).isoformat()
        if m := re.fullmatch(r"(\d{1,2}) ([A-Za-z]+)\.?,? (\d{4})", s):
            if m[2].lower() in _MONTHS:
                return date(int(m[3]), _MONTHS[m[2].lower()], int(m[1])).isoformat()
    except ValueError as exc:
        raise FactTypeMismatch(f"{field_name}: {text!r} is not a real calendar date") from exc

    raise FactTypeMismatch(
        f"{field_name}: could not read {text!r} as a date. Use YYYY-MM-DD, or quote the "
        "date exactly as printed."
    )
