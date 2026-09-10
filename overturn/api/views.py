"""JSON views of the deterministic layer, shaped for the interface.

The interface renders; it does not decide. Every judgment it displays — what is missing,
what is critical, how close a deadline is, which paragraph rests on an unverified fact —
arrives here already computed, so the screen can never disagree with the engine.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from overturn.engine.anomalies import Anomaly
from overturn.engine.argument import ArgumentPlan
from overturn.engine.deadlines import ComputedDeadline, DeadlineComputation, Pressure
from overturn.engine.escalation import Escalation
from overturn.engine.evidence import Readiness
from overturn.extraction import DEFAULT_FIELDS
from overturn.ledger.fields import EVIDENCE_PREFIX, get_field
from overturn.ledger.schema import Document, Fact, Provenance, StateTransition
from overturn.pipeline import CaseSnapshot

_PRESSURE_RANK = {p: i for i, p in enumerate(Pressure)}


def provenance_view(p: Provenance | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"doc_id": p.doc_id, "page": p.page, "char_span": list(p.char_span), "quote": p.quote}


def fact_view(field: str, fact: Fact | None, *, required: bool = False) -> dict[str, Any]:
    spec = get_field(field)
    assert spec is not None
    base = {
        "field": field,
        "kind": spec.kind.value,
        "origin": spec.origin.value,
        "critical": spec.is_critical,
        "pii": spec.pii,
        "description": spec.description,
        "required": required,
    }
    if fact is None:
        return {
            **base,
            "status": "not_looked_for",
            "value": None,
            "confidence": None,
            "provenance": None,
            "reason": "No document has been read for this field yet.",
            "verified_by": None,
            "recorded_by": None,
            "conflict": [],
            "packet_ready": False,
        }
    return {
        **base,
        "status": fact.status.value,
        "value": fact.value,
        "confidence": fact.confidence,
        "provenance": provenance_view(fact.provenance),
        "reason": fact.reason,
        "regime": fact.regime,
        "verified_by": fact.verified_by,
        "recorded_by": fact.recorded_by,
        "conflict": [
            {"reads": c.reads, "provenance": provenance_view(c.provenance)} for c in fact.conflict
        ],
        "packet_ready": fact.is_packet_ready,
    }


def ledger_view(snapshot: CaseSnapshot) -> list[dict[str, Any]]:
    """Every field the advocate should see, including the ones nobody has found yet.

    Fields never looked for are listed with their own status rather than left out, so an
    empty box on screen always means something specific.
    """
    required = snapshot.pack.required_facts if snapshot.pack else ()
    names = list(DEFAULT_FIELDS) + [f for f in required if f not in DEFAULT_FIELDS]
    for name in snapshot.case.facts:
        if name not in names and not name.startswith(EVIDENCE_PREFIX):
            names.append(name)
    return [fact_view(n, snapshot.case.fact(n), required=n in required) for n in names]


def deadline_view(d: ComputedDeadline, today: date) -> dict[str, Any]:
    return {
        "field": d.field,
        "due": d.due.isoformat(),
        "basis": d.basis.value,
        "regime": d.regime.value if d.regime else None,
        "rule": d.rule,
        "anchor_field": d.anchor_field,
        "anchor_date": d.anchor_date.isoformat(),
        "anchor_is_estimated": d.anchor_is_estimated,
        "days_remaining": d.days_remaining(today),
        "pressure": d.pressure(today).value,
        "met_on": d.met_on.isoformat() if d.met_on else None,
    }


def deadlines_view(c: DeadlineComputation, today: date) -> dict[str, Any]:
    return {
        "regime": c.regime.value if c.regime else None,
        "regime_blocked_by": list(c.regime_blocked_by),
        "deadlines": [deadline_view(d, today) for d in c.deadlines],
        "blocked": [
            {
                "field": b.field,
                "missing_fields": list(b.missing_fields),
                "explanation": b.explanation,
            }
            for b in c.blocked
        ],
        "highest_pressure": c.highest_pressure(today).value,
    }


def escalation_view(e: Escalation) -> dict[str, Any]:
    return {
        "id": e.escalation_id,
        "trigger": int(e.trigger),
        "trigger_label": e.trigger_label,
        "subject": e.subject,
        "question": e.question,
        "why_it_matters": e.why_it_matters,
        "options": list(e.options),
        "blocking": e.blocking,
        "detail": e.detail,
    }


def readiness_view(r: Readiness | None) -> dict[str, Any] | None:
    if r is None:
        return None

    def item(i):
        return {
            "id": i.id,
            "label": i.label,
            "source": i.source,
            "human_only": i.human_only,
            "blocking": i.blocking,
        }

    return {
        "packet_ready": r.is_packet_ready,
        "summary": r.summary(),
        "present": [item(i) for i in r.present_evidence],
        "missing_blocking": [item(i) for i in r.missing_blocking_evidence],
        "missing_optional": [item(i) for i in r.missing_optional_evidence],
        "fact_gaps": [
            {"field": g.field, "status": g.status.value if g.status else None, "reason": g.reason}
            for g in r.fact_gaps
        ],
        "unverified_critical": list(r.unverified_critical_facts),
    }


def plan_view(p: ArgumentPlan | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {
        "pack": p.pack.qualified_name,
        "included": [
            {
                "step_id": s.step_id,
                "text": s.text,
                "evidence": list(s.evidence),
                "rests_on_unverified": s.rests_on_unverified,
                "citations": [
                    {
                        "field": c.field,
                        "value_text": c.value_text,
                        "status": c.status.value,
                        "critical": c.critical,
                        "provenance": provenance_view(c.provenance),
                    }
                    for c in s.citations
                ],
            }
            for s in p.included
        ],
        "omitted": [
            {
                "step_id": s.step_id,
                "reason": s.reason,
                "missing_facts": list(s.missing_facts),
                "missing_evidence": list(s.missing_evidence),
                "is_gap": s.is_gap,
            }
            for s in p.omitted
        ],
    }


def anomaly_view(a: Anomaly) -> dict[str, Any]:
    return {
        "kind": a.kind.value,
        "severity": a.severity.value,
        "doc_id": a.doc_id,
        "page": a.page,
        "char_span": list(a.char_span) if a.char_span else None,
        "excerpt": a.excerpt,
        "explanation": a.explanation,
    }


def document_view(d: Document) -> dict[str, Any]:
    return {
        "doc_id": d.doc_id,
        "kind": d.kind,
        "filename": d.filename,
        "pages": d.pages,
        "ingest_method": d.ingest_method,
        "ocr_confidence": d.ocr_confidence,
        "trust_zone": d.trust_zone.value,
        "ingested_at": d.ingested_at.isoformat(),
    }


def history_view(t: StateTransition) -> dict[str, Any]:
    return {
        "from": t.from_state.value if t.from_state else None,
        "to": t.to_state.value,
        "at": t.at.isoformat(),
        "by": t.by,
        "reason": t.reason,
    }


def snapshot_view(s: CaseSnapshot, today: date) -> dict[str, Any]:
    case = s.case
    return {
        "case_id": case.case_id,
        "state": case.state.value,
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
        "pack": {"id": s.pack.id, "name": s.pack.display_name, "version": s.pack.version}
        if s.pack
        else None,
        "classification": {
            "explanation": s.classification.explanation,
            "ambiguous": s.classification.ambiguous,
            "blocked_by": list(s.classification.blocked_by),
            "candidates": [c.describe() for c in s.classification.candidates],
        },
        "documents": [document_view(d) for d in case.documents],
        "ledger": ledger_view(s),
        "readiness": readiness_view(s.readiness),
        "deadlines": deadlines_view(s.deadlines, today),
        "escalations": [escalation_view(e) for e in s.escalations],
        "silent": list(s.gate.silent),
        "anomalies": [anomaly_view(a) for a in s.anomalies],
        "plan": plan_view(s.plan),
        "history": [history_view(t) for t in case.history],
        "answers": [
            {"id": a.escalation_id, "answer": a.answer, "by": a.by, "at": a.at.isoformat()}
            for a in case.answers.values()
        ],
    }


def case_summary(s: CaseSnapshot, today: date) -> dict[str, Any]:
    """One row of the morning queue: why this case wants attention today, if it does."""
    still_open = [d for d in s.deadlines.deadlines if d.met_on is None]
    next_deadline = min(still_open, key=lambda d: d.due, default=None)
    top = s.escalations[0] if s.escalations else None
    blocking = [e for e in s.escalations if e.blocking]
    if blocking:
        top = min(blocking, key=lambda e: int(e.trigger) if e.trigger != 3 else 0)
    return {
        "case_id": s.case.case_id,
        "state": s.case.state.value,
        "pack": s.pack.display_name if s.pack else None,
        "issuer": s.case.value("plan.issuer"),
        "service": s.case.value("service.description"),
        "escalation_count": len(s.escalations),
        "blocking_count": len(blocking),
        "top": escalation_view(top) if top else None,
        "next_deadline": deadline_view(next_deadline, today) if next_deadline else None,
        "highest_pressure": s.deadlines.highest_pressure(today).value,
        "updated_at": s.case.updated_at.isoformat(),
    }


def queue_order(summary: dict[str, Any]) -> tuple:
    """Deadline pressure first, then how much is blocked, then the soonest clock."""
    pressure = _PRESSURE_RANK[Pressure(summary["highest_pressure"])]
    remaining = summary["next_deadline"]["days_remaining"] if summary["next_deadline"] else 10**6
    return (-pressure, -summary["blocking_count"], remaining)
