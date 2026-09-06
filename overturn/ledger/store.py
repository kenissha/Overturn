"""Case persistence and the write audit.

Two responsibilities:

*Storage.* One JSON file per case. A single-user tool working tens of files does not need
a database, and a file the advocate can open and read is worth more here than a schema
migration story.

*Audit.* Every attempt to write a fact is appended to a JSONL log — including the attempts
that were refused. A refusal is not an error to be swallowed: if an agent tried to write a
deadline, or to invent a field, that attempt is evidence about the document it was reading.
The red-team suite asserts against this log.

PII never enters the audit log. Fields marked ``pii`` in the taxonomy are recorded by name
and shape only, never by value.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from overturn.ledger.errors import DocumentNotFound
from overturn.ledger.fields import get_field
from overturn.ledger.schema import Case, Fact, utcnow

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_case_id() -> str:
    """A lexicographically sortable, collision-resistant case id.

    Time-ordered so that listing cases on disk lists them in creation order without
    opening any of them.
    """
    ms = int(datetime.now(UTC).timestamp() * 1000)
    time_part = ""
    for _ in range(10):
        ms, rem = divmod(ms, 32)
        time_part = _CROCKFORD[rem] + time_part
    rand_part = "".join(secrets.choice(_CROCKFORD) for _ in range(8))
    return f"case_{time_part}{rand_part}"


def new_doc_id(kind: str) -> str:
    return f"doc_{kind}_{secrets.token_hex(4)}"


class AuditEvent(dict):
    """A single line in the write audit. A plain dict so it stays trivially serialisable."""


class CaseStore:
    """File-backed case storage with an append-only write audit."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.cases_dir = self.root / "cases"
        self.audit_dir = self.root / "audit"
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    # -- cases --------------------------------------------------------------------

    def path_for(self, case_id: str) -> Path:
        _reject_traversal(case_id)
        return self.cases_dir / f"{case_id}.json"

    def exists(self, case_id: str) -> bool:
        return self.path_for(case_id).exists()

    def create(self, case_id: str | None = None) -> Case:
        case = Case(case_id=case_id or new_case_id())
        self.save(case)
        return case

    def load(self, case_id: str) -> Case:
        path = self.path_for(case_id)
        if not path.exists():
            raise FileNotFoundError(f"No such case: {case_id}")
        return Case.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, case: Case) -> None:
        case.updated_at = utcnow()
        _atomic_write(
            self.path_for(case.case_id),
            case.model_dump_json(indent=2),
        )

    def list_case_ids(self) -> list[str]:
        return sorted(p.stem for p in self.cases_dir.glob("case_*.json"))

    # -- audit --------------------------------------------------------------------

    def audit_path(self, case_id: str) -> Path:
        _reject_traversal(case_id)
        return self.audit_dir / f"{case_id}.jsonl"

    def record_write(
        self,
        case_id: str,
        *,
        actor: str,
        field: str,
        outcome: str,
        detail: str | None = None,
        error_type: str | None = None,
        value: Any = None,
    ) -> AuditEvent:
        """Append one write attempt to the audit log.

        ``outcome`` is ``accepted`` or ``refused``. Refusals carry the error type so the
        red-team suite can assert on *why* a write was stopped, not merely that it was.
        """
        event = AuditEvent(
            at=utcnow().isoformat(),
            case_id=case_id,
            actor=actor,
            field=field,
            outcome=outcome,
            error_type=error_type,
            detail=detail,
            value=_redact(field, value),
        )
        with self.audit_path(case_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def read_audit(self, case_id: str) -> list[AuditEvent]:
        path = self.audit_path(case_id)
        if not path.exists():
            return []
        return [
            AuditEvent(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    # -- writes -------------------------------------------------------------------

    def put_fact(self, case: Case, fact: Fact) -> None:
        """Attach a validated fact to a case, checking that its source exists.

        :class:`Fact` guarantees a value has *a* source; this checks the source is a
        document actually on this case, closing the gap where an agent cites a plausible
        but fictional ``doc_id``.
        """
        if fact.provenance is not None and case.document(fact.provenance.doc_id) is None:
            raise DocumentNotFound(
                f"{fact.field}: provenance cites {fact.provenance.doc_id!r}, which is not "
                "a document on this case."
            )
        for side in fact.conflict:
            if case.document(side.provenance.doc_id) is None:
                raise DocumentNotFound(
                    f"{fact.field}: conflict cites {side.provenance.doc_id!r}, which is "
                    "not a document on this case."
                )
        case.facts[fact.field] = fact


def _redact(field: str, value: Any) -> Any:
    """Replace PII values with a shape description before they reach a log."""
    if value is None:
        return None
    spec = get_field(field)
    if spec is not None and spec.pii:
        return f"<redacted {spec.kind.value}, len={len(str(value))}>"
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "..."
    return value


def _reject_traversal(case_id: str) -> None:
    if not case_id or "/" in case_id or "\\" in case_id or ".." in case_id:
        raise ValueError(f"Unsafe case id: {case_id!r}")


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file and replace, so a crash never leaves a half-written case."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
