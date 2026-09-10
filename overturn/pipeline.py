"""The case pipeline: what happens to a denial file, and in what order.

    ingest    a document is stored, normalised and scanned for anomalies
    extract   the extraction agent reads a denial letter into the ledger (untrusted zone)
    evaluate  the deterministic layer classifies, assesses, computes deadlines, plans the
              argument and runs the escalation gate
    answer    a person replies to an escalation, and the case is evaluated again

``evaluate`` reads only the ledger and calls no model, so it can run on every scheduler
tick. Its one side effect is moving the case between the states the system is allowed to
set. Filing, and everything after it, is recorded by a person: nothing in this module can
move a case there on its own, and a test holds that line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from overturn.engine.anomalies import Anomaly, AnomalyKind, Severity, scan_document
from overturn.engine.argument import ArgumentPlan, plan_argument
from overturn.engine.deadlines import DeadlineComputation, compute_deadlines
from overturn.engine.escalation import Escalation, GateResult, Trigger, escalation_id
from overturn.engine.escalation import evaluate as run_gate
from overturn.engine.evidence import Readiness, assess
from overturn.engine.packs import PackRegistry, RulePack
from overturn.engine.rules import Classification, classify
from overturn.extraction import DEFAULT_FIELDS, ExtractionInput, Extractor
from overturn.ledger.documents import DocumentText
from overturn.ledger.fields import FieldOrigin, get_field
from overturn.ledger.schema import (
    Case,
    CaseState,
    Document,
    EscalationAnswer,
    Fact,
    FactStatus,
    FactValue,
    StateTransition,
    TrustZone,
    utcnow,
)
from overturn.ledger.store import CaseStore, new_doc_id
from overturn.tools.ledger_tools import LedgerWriter
from overturn.tools.quoting import coerce_value

SYSTEM_ACTOR = "Pipeline@v1"

EXTRACTED_KINDS = frozenset({"denial_letter"})
"""Document kinds the extraction agent reads. Supporting documents — a physician's letter,
clinical notes — are recorded as evidence on file, not mined for denial facts."""

PERSON_ONLY_STATES = frozenset(
    {
        CaseState.SUBMITTED,
        CaseState.AWAITING_RESPONSE,
        CaseState.DECISION,
        CaseState.RESOLVED_OVERTURNED,
        CaseState.RESOLVED_UPHELD,
        CaseState.EXTERNAL_REVIEW_ELIGIBLE,
        CaseState.EXTERNAL_REVIEW,
        CaseState.CLOSED_DEADLINE_MISSED,
    }
)
"""States only a person moves a case into. The pipeline reads them and never sets them."""

AWAITING_DECISION = frozenset(
    {
        CaseState.SUBMITTED,
        CaseState.AWAITING_RESPONSE,
        CaseState.DECISION,
        CaseState.EXTERNAL_REVIEW,
    }
)
"""States in which an appeal has gone out and a decision can be recorded."""


@dataclass(frozen=True, slots=True)
class CaseSnapshot:
    """Everything the deterministic layer knows about a case, at one moment."""

    case: Case
    pack: RulePack | None
    classification: Classification
    readiness: Readiness | None
    deadlines: DeadlineComputation
    plan: ArgumentPlan | None
    gate: GateResult
    anomalies: tuple[Anomaly, ...]

    @property
    def escalations(self) -> tuple[Escalation, ...]:
        return self.gate.escalations


class Pipeline:
    def __init__(
        self,
        store: CaseStore,
        registry: PackRegistry,
        extractor: Extractor | None = None,
        *,
        extractor_actor: str = "ExtractionAgent@v1",
        fields: tuple[str, ...] = DEFAULT_FIELDS,
    ) -> None:
        self.store = store
        self.registry = registry
        self.extractor = extractor
        self.extractor_actor = extractor_actor
        self.fields = fields

    # -- documents -----------------------------------------------------------------

    def ingest(
        self,
        case_id: str,
        *,
        filename: str,
        kind: str,
        raw_pages: list[str],
        ingest_method: str = "text",
        ocr_confidence: float | None = None,
        doc_id: str | None = None,
    ) -> Document:
        """Store a document and scan it. Nothing reads it for facts yet."""
        case = self.store.load(case_id)
        doc_id = doc_id or new_doc_id(kind)
        text = DocumentText.from_pages(doc_id, raw_pages)
        anomalies = scan_document(doc_id, raw_pages, ocr_confidence=ocr_confidence)

        document = Document(
            doc_id=doc_id,
            kind=kind,
            filename=filename,
            pages=max(1, len(raw_pages)),
            ingest_method=ingest_method,
            ocr_confidence=ocr_confidence,
            trust_zone=TrustZone.UNTRUSTED,
            sha256=text.sha256(),
        )
        self.store.save_document_text(
            case_id,
            doc_id,
            raw_pages=list(raw_pages),
            pages=list(text.pages),
            anomalies=[_anomaly_to_dict(a) for a in anomalies],
        )
        case.documents.append(document)
        self.store.save(case)
        return document

    def document_text(self, case_id: str, doc_id: str) -> DocumentText:
        data = self.store.load_document_text(case_id, doc_id)
        return DocumentText(doc_id=doc_id, pages=tuple(data["pages"]))

    def anomalies(self, case: Case) -> tuple[Anomaly, ...]:
        found: list[Anomaly] = []
        for document in case.documents:
            data = self.store.load_document_text(case.case_id, document.doc_id)
            found.extend(_anomaly_from_dict(a) for a in data.get("anomalies", []))
        return tuple(found)

    def pending_documents(self, case: Case) -> list[Document]:
        return [
            d
            for d in case.documents
            if d.kind in EXTRACTED_KINDS
            and not self.store.load_document_text(case.case_id, d.doc_id).get("extracted_at")
        ]

    # -- extraction ----------------------------------------------------------------

    def extract(self, case_id: str, doc_id: str) -> None:
        """Hand one document to the extractor, bound to that document alone."""
        if self.extractor is None:
            raise RuntimeError("No extractor configured; this pipeline cannot read documents.")
        case = self.store.load(case_id)
        text = self.document_text(case_id, doc_id)
        writer = LedgerWriter(self.store, case, actor=self.extractor_actor, texts={doc_id: text})
        self.extractor(ExtractionInput(doc_id=doc_id, pages=text.pages, fields=self.fields), writer)
        self.store.mark_extracted(case_id, doc_id)

    def extract_pending(self, case_id: str) -> int:
        pending = self.pending_documents(self.store.load(case_id))
        for document in pending:
            self.extract(case_id, document.doc_id)
        return len(pending)

    # -- evaluation ----------------------------------------------------------------

    def evaluate(self, case_id: str, *, today: date | None = None) -> CaseSnapshot:
        """Run the deterministic layer over the ledger. No model, no documents read."""
        case = self.store.load(case_id)
        today = today or date.today()

        classification = classify(case, self.registry)
        pack = classification.selected
        if pack is None and case.rule_pack:
            pack = self.registry.resolve(case.rule_pack)  # a person chose it

        readiness = assess(case, pack) if pack else None
        deadlines = compute_deadlines(case)
        anomalies = self.anomalies(case)
        settled = case.state in PERSON_ONLY_STATES  # filed: preparation is moot
        gate = run_gate(
            case,
            classification=None if settled else classification,
            readiness=None if settled else readiness,
            deadlines=deadlines,
            anomalies=anomalies,
            today=today,
            resolved=frozenset(case.answers),
        )
        plan = plan_argument(case, pack) if pack else None

        changed = False
        if pack is not None and case.rule_pack != pack.qualified_name:
            case.rule_pack = pack.qualified_name
            changed = True

        target = derive_state(case, pack, readiness)
        if target is not case.state:
            case.history.append(
                StateTransition(
                    from_state=case.state,
                    to_state=target,
                    by=SYSTEM_ACTOR,
                    reason=_transition_reason(target, classification, readiness),
                )
            )
            case.state = target
            changed = True

        if changed:
            self.store.save(case)

        return CaseSnapshot(
            case=case,
            pack=pack,
            classification=classification,
            readiness=readiness,
            deadlines=deadlines,
            plan=plan,
            gate=gate,
            anomalies=anomalies,
        )

    def process(self, case_id: str, *, today: date | None = None) -> CaseSnapshot:
        """Read anything unread, then evaluate. Safe to call repeatedly."""
        if self.extractor is not None:
            self.extract_pending(case_id)
        return self.evaluate(case_id, today=today)

    # -- people --------------------------------------------------------------------

    def answer(
        self, case_id: str, esc_id: str, answer: str, *, by: str, today: date | None = None
    ) -> CaseSnapshot:
        """Record a person's reply to an open escalation, and apply what it settles."""
        open_now = {e.escalation_id: e for e in self.evaluate(case_id, today=today).escalations}
        escalation = open_now.get(esc_id)
        if escalation is None:
            raise KeyError(f"No open escalation {esc_id} on {case_id}")

        case = self.store.load(case_id)
        self._apply(case, escalation, answer, by)
        case.answers[esc_id] = EscalationAnswer(escalation_id=esc_id, answer=answer, by=by)
        self.store.save(case)
        return self.evaluate(case_id, today=today)

    def state_fact(
        self, case_id: str, field: str, value: FactValue, *, by: str, today: date | None = None
    ) -> CaseSnapshot:
        """A person supplies a value that no document on file states."""
        case = self.store.load(case_id)
        case.facts[field] = _human_answer(field, value, by)
        self.store.save(case)
        return self.evaluate(case_id, today=today)

    def confirm_fact(
        self, case_id: str, field: str, *, by: str, today: date | None = None
    ) -> CaseSnapshot:
        """A person checks an extracted value against the original and confirms it."""
        case = self.store.load(case_id)
        fact = case.fact(field)
        if fact is None or fact.status is not FactStatus.EXTRACTED:
            raise ValueError(f"{field} has no extracted value to confirm")
        case.facts[field] = _verified(fact, by)
        self.store.save(case)
        return self.evaluate(case_id, today=today)

    def attach_evidence(
        self, case_id: str, evidence_id: str, *, by: str, today: date | None = None
    ) -> CaseSnapshot:
        """A person records that a required document is now on file."""
        return self.state_fact(case_id, f"evidence.{evidence_id}", True, by=by, today=today)

    def mark_filed(
        self, case_id: str, filed_on: date, *, by: str, today: date | None = None
    ) -> CaseSnapshot:
        """Record that a person filed the appeal. Overturn itself never submits anything."""
        case = self.store.load(case_id)
        if case.state is CaseState.EXTERNAL_REVIEW_ELIGIBLE:
            field, target, what = (
                "appeal.external_review_filed_date",
                CaseState.EXTERNAL_REVIEW,
                "External review request",
            )
        elif case.state in PERSON_ONLY_STATES:
            raise ValueError(f"{case_id} is already {case.state.value}")
        else:
            field, target, what = "appeal.filed_date", CaseState.SUBMITTED, "Appeal"
        case.facts[field] = _human_answer(field, filed_on, by)
        case.history.append(
            StateTransition(
                from_state=case.state,
                to_state=target,
                by=by,
                reason=f"{what} filed by {by} from state {case.state.value}. Overturn "
                "does not submit anything.",
            )
        )
        case.state = target
        self.store.save(case)
        return self.evaluate(case_id, today=today)

    def record_decision(
        self,
        case_id: str,
        outcome: str,
        decided_on: date,
        *,
        by: str,
        today: date | None = None,
    ) -> CaseSnapshot:
        """Record a decision on the appeal, as the advocate received it.

        Overturned resolves the file. An upheld internal appeal is a final internal adverse
        determination: the case becomes eligible for external review, whose clock runs from
        the date of the decision. An upheld external review resolves the file.
        """
        if outcome not in ("overturned", "upheld"):
            raise ValueError("outcome must be 'overturned' or 'upheld'")
        case = self.store.load(case_id)
        if case.state not in AWAITING_DECISION:
            raise ValueError(
                f"{case_id} has no appeal awaiting a decision; it is {case.state.value}"
            )
        external = case.state is CaseState.EXTERNAL_REVIEW
        if outcome == "overturned":
            target = CaseState.RESOLVED_OVERTURNED
        elif external:
            target = CaseState.RESOLVED_UPHELD
        else:
            target = CaseState.EXTERNAL_REVIEW_ELIGIBLE
            case.facts["appeal.decision_date"] = _human_answer(
                "appeal.decision_date", decided_on, by
            )
            case.facts["denial.is_final"] = _human_answer("denial.is_final", True, by)
        case.facts["appeal.outcome"] = _human_answer("appeal.outcome", outcome, by)
        stage = "external review" if external else "internal appeal"
        case.history.append(
            StateTransition(
                from_state=case.state,
                to_state=target,
                by=by,
                reason=f"The {stage} was {outcome}, decided {decided_on.isoformat()}.",
            )
        )
        case.state = target
        self.store.save(case)
        return self.evaluate(case_id, today=today)

    # -- internals -----------------------------------------------------------------

    def _apply(self, case: Case, escalation: Escalation, answer: str, by: str) -> None:
        """Turn an answer into ledger state, where the answer settles something."""
        if escalation.trigger is Trigger.DEADLINE_PRESSURE and answer == "Close the case":
            case.history.append(
                StateTransition(
                    from_state=case.state,
                    to_state=CaseState.CLOSED_DEADLINE_MISSED,
                    by=by,
                    reason="Closed by a person after the filing window passed.",
                )
            )
            case.state = CaseState.CLOSED_DEADLINE_MISSED
            return
        if escalation.trigger is not Trigger.HUMAN_JUDGMENT:
            return  # other deadline and anomaly answers are recorded, not applied

        if escalation.subject == "classification":
            chosen = next((p for p in self.registry if p.display_name == answer), None)
            if chosen is not None:
                case.rule_pack = chosen.qualified_name
            return

        field = escalation.subject
        spec = get_field(field)
        if spec is None:
            return

        verify_id = escalation_id(case.case_id, Trigger.HUMAN_JUDGMENT, f"verify:{field}")
        if escalation.escalation_id == verify_id:
            fact = case.fact(field)
            if answer == "Confirm" and fact is not None and fact.status is FactStatus.EXTRACTED:
                case.facts[field] = _verified(fact, by)
            return

        if spec.origin is FieldOrigin.HUMAN and answer in ("Yes", "No"):
            case.facts[field] = _human_answer(field, answer == "Yes", by)


def derive_state(case: Case, pack: RulePack | None, readiness: Readiness | None) -> CaseState:
    """Where the evidence puts a case. Never a state only a person may set."""
    if case.state in PERSON_ONLY_STATES:
        return case.state
    if pack is None or readiness is None:
        return CaseState.INTAKE
    if readiness.is_packet_ready:
        return CaseState.PACKET_READY
    if any(item.blocking for item in readiness.human_only_gaps):
        return CaseState.AWAITING_DOCUMENT
    return CaseState.EVIDENCE_GAP


def _transition_reason(
    target: CaseState, classification: Classification, readiness: Readiness | None
) -> str:
    if target is CaseState.INTAKE:
        return classification.explanation
    if target is CaseState.PACKET_READY:
        return "Every required fact is established and every required document is on file."
    if target is CaseState.AWAITING_DOCUMENT and readiness is not None:
        labels = "; ".join(i.label for i in readiness.human_only_gaps if i.blocking)
        return f"Waiting on a document only a person can obtain: {labels}."
    return readiness.summary() if readiness is not None else classification.explanation


def _human_answer(field: str, value: FactValue | date, by: str) -> Fact:
    if isinstance(value, date):
        value = value.isoformat()
    return Fact(
        field=field,
        value=coerce_value(field, value),
        status=FactStatus.HUMAN_ANSWERED,
        verified_by=by,
        verified_at=utcnow(),
        recorded_by=by,
    )


def _verified(fact: Fact, by: str) -> Fact:
    data = fact.model_dump()
    data.update(status=FactStatus.HUMAN_VERIFIED, verified_by=by, verified_at=utcnow())
    return Fact.model_validate(data)


def _anomaly_to_dict(a: Anomaly) -> dict:
    return {
        "kind": a.kind.value,
        "severity": a.severity.value,
        "doc_id": a.doc_id,
        "page": a.page,
        "char_span": list(a.char_span) if a.char_span else None,
        "excerpt": a.excerpt,
        "explanation": a.explanation,
    }


def _anomaly_from_dict(d: dict) -> Anomaly:
    span = d.get("char_span")
    return Anomaly(
        kind=AnomalyKind(d["kind"]),
        severity=Severity(d["severity"]),
        doc_id=d["doc_id"],
        page=d.get("page"),
        char_span=tuple(span) if span else None,
        excerpt=d["excerpt"],
        explanation=d["explanation"],
    )
