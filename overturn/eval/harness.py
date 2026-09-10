"""The evaluation harness.

Runs any extractor over the corpus, through the real ledger tools, and scores what landed
in the ledger against the answer key. The extractor is handed exactly what a production
extraction agent is handed — the document's normalised text and the list of fields — and
never the answer key.

Writes go through :class:`LedgerWriter`, the same object the agent uses in production.
That matters: a fabricated citation is refused at write time here exactly as it would be
in use, so the numbers describe the system as built rather than the model in isolation.

The metrics that matter most are the two the product is sold on:

``hallucination_rate``
    Of the values the system asserted, how many were wrong or had no basis in the letter.

``correct_abstention``
    Of the fields the letter does not establish, how many were explicitly recorded as
    missing. Silence does not count: abstention has to be an action.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path

from overturn.engine.anomalies import scan_document
from overturn.engine.deadlines import compute_deadlines
from overturn.engine.packs import PackRegistry
from overturn.engine.rules import classify
from overturn.eval.corpus import EXTRACTION_FIELDS, Sample
from overturn.extraction import ExtractionInput, Extractor
from overturn.ledger.documents import DocumentText
from overturn.ledger.fields import FactKind, get_field
from overturn.ledger.schema import (
    Case,
    Document,
    Fact,
    FactStatus,
    FactValue,
    Provenance,
    TrustZone,
)
from overturn.ledger.store import CaseStore
from overturn.tools.ledger_tools import LedgerWriter

# --- per-field outcomes -----------------------------------------------------------------


class Outcome(StrEnum):
    CORRECT = "correct"
    WRONG_VALUE = "wrong_value"
    FALSE_ABSTENTION = "false_abstention"
    UNATTEMPTED = "unattempted"
    UNSUPPORTED_VALUE = "unsupported_value"
    CORRECT_ABSTENTION = "correct_abstention"
    SILENT_ABSENT = "silent_absent"


ASSERTED = (Outcome.CORRECT, Outcome.WRONG_VALUE, Outcome.UNSUPPORTED_VALUE)
HALLUCINATED = (Outcome.WRONG_VALUE, Outcome.UNSUPPORTED_VALUE)


def values_match(field_name: str, expected: FactValue, actual: FactValue) -> bool:
    """Whether an extracted value is the gold value, judged by the field's kind."""
    spec = get_field(field_name)
    kind = spec.kind if spec else FactKind.STRING

    if kind is FactKind.STRING_LIST:
        if not isinstance(actual, list) or not isinstance(expected, list):
            return False
        return {a.strip().upper() for a in actual} == {e.strip().upper() for e in expected}

    if kind is FactKind.STRING:
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        a = " ".join(actual.split()).casefold().strip(" .,;")
        e = " ".join(expected.split()).casefold().strip(" .,;")
        return a == e or (len(a) >= 8 and (a in e or e in a))

    return actual == expected


def score_field(field_name: str, gold_value: FactValue, fact: Fact | None) -> Outcome:
    if gold_value is not None:
        if fact is None:
            return Outcome.UNATTEMPTED
        if fact.status is FactStatus.MISSING or not fact.is_known:
            return Outcome.FALSE_ABSTENTION
        return (
            Outcome.CORRECT
            if values_match(field_name, gold_value, fact.value)
            else (Outcome.WRONG_VALUE)
        )

    if fact is None:
        return Outcome.SILENT_ABSENT
    if fact.status is FactStatus.MISSING:
        return Outcome.CORRECT_ABSTENTION
    if fact.is_known:
        return Outcome.UNSUPPORTED_VALUE
    return Outcome.SILENT_ABSENT


# --- per-sample result ------------------------------------------------------------------


@dataclass
class SampleResult:
    sample_id: str
    tags: list[str]
    outcomes: dict[str, Outcome]
    refusals: int
    classification_correct: bool
    classification_detail: str
    deadline_correct: bool
    deadline_detail: str
    anomaly_expected: list[str]
    anomaly_found: list[str]
    planted_value_extracted: bool = False


def _gold_case(sample: Sample) -> Case:
    """The case as it would be if extraction were perfect. Used to score the engine."""
    case = Case(case_id=f"case_gold_{sample.sample_id}")
    for name, gold in sample.gold.items():
        if gold.value is None:
            continue
        case.facts[name] = Fact(
            field=name,
            value=gold.value,
            status=FactStatus.EXTRACTED,
            confidence=1.0,
            provenance=Provenance(doc_id=sample.doc_id, page=gold.page or 1, char_span=(0, 1)),
            recorded_by="gold",
        )
    return case


def run_sample(
    sample: Sample,
    extractor: Extractor,
    registry: PackRegistry,
    root: Path,
    actor: str = "extractor",
) -> SampleResult:
    store = CaseStore(root)
    case = store.create(case_id=f"case_{sample.sample_id}")
    text = DocumentText.from_pages(sample.doc_id, sample.pages)
    case.documents.append(
        Document(
            doc_id=sample.doc_id,
            kind="denial_letter",
            filename=f"{sample.sample_id}.txt",
            pages=len(sample.pages),
            ingest_method="text",
            trust_zone=TrustZone.UNTRUSTED,
            sha256=text.sha256(),
        )
    )
    store.save(case)

    writer = LedgerWriter(store, case, actor=actor, texts={sample.doc_id: text})
    extractor(
        ExtractionInput(doc_id=sample.doc_id, pages=text.pages, fields=EXTRACTION_FIELDS),
        writer,
    )
    case = store.load(case.case_id)

    outcomes = {
        name: score_field(name, sample.gold[name].value, case.fact(name))
        for name in EXTRACTION_FIELDS
    }
    refusals = sum(1 for e in store.read_audit(case.case_id) if e["outcome"] == "refused")

    # Classification, run on what extraction actually produced.
    result = classify(case, registry)
    got_pack = result.selected.id if result.selected else None
    if sample.expected_ambiguous:
        classification_correct = result.ambiguous
    else:
        classification_correct = got_pack == sample.expected_pack and not result.ambiguous
    classification_detail = (
        f"expected {'ambiguous' if sample.expected_ambiguous else sample.expected_pack}, "
        f"got {'ambiguous' if result.ambiguous else got_pack}"
    )

    # Deadlines: the engine on extracted facts versus the engine on the answer key.
    want = compute_deadlines(_gold_case(sample)).get("deadline.internal_appeal_due")
    got = compute_deadlines(case).get("deadline.internal_appeal_due")
    want_due = want.due if want else None
    got_due = got.due if got else None
    deadline_correct = want_due == got_due

    found = sorted({a.kind.value for a in scan_document(sample.doc_id, sample.pages)})

    planted = False
    if "fact_poisoning" in sample.tags:
        fact = case.fact("denial.notice_date")
        planted = bool(
            fact and fact.is_known and fact.value != sample.gold["denial.notice_date"].value
        )

    return SampleResult(
        sample_id=sample.sample_id,
        tags=sample.tags,
        outcomes=outcomes,
        refusals=refusals,
        classification_correct=classification_correct,
        classification_detail=classification_detail,
        deadline_correct=deadline_correct,
        deadline_detail=f"expected {want_due}, got {got_due}",
        anomaly_expected=sample.expected_anomalies,
        anomaly_found=found,
        planted_value_extracted=planted,
    )


# --- the report ---------------------------------------------------------------------------


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


@dataclass
class EvalReport:
    extractor_name: str
    results: list[SampleResult]
    corpus_notes: dict[str, int] = field(default_factory=dict)

    @property
    def outcome_counts(self) -> Counter[Outcome]:
        return Counter(o for r in self.results for o in r.outcomes.values())

    @property
    def field_accuracy(self) -> float | None:
        c = self.outcome_counts
        with_value = (
            c[Outcome.CORRECT]
            + c[Outcome.WRONG_VALUE]
            + c[Outcome.FALSE_ABSTENTION]
            + c[Outcome.UNATTEMPTED]
        )
        return _ratio(c[Outcome.CORRECT], with_value)

    @property
    def hallucination_rate(self) -> float | None:
        c = self.outcome_counts
        return _ratio(sum(c[o] for o in HALLUCINATED), sum(c[o] for o in ASSERTED))

    @property
    def correct_abstention(self) -> float | None:
        c = self.outcome_counts
        absent = (
            c[Outcome.CORRECT_ABSTENTION] + c[Outcome.UNSUPPORTED_VALUE] + c[Outcome.SILENT_ABSENT]
        )
        return _ratio(c[Outcome.CORRECT_ABSTENTION], absent)

    @property
    def classification_accuracy(self) -> float | None:
        return _ratio(sum(r.classification_correct for r in self.results), len(self.results))

    @property
    def deadline_accuracy(self) -> float | None:
        return _ratio(sum(r.deadline_correct for r in self.results), len(self.results))

    @property
    def anomaly_recall(self) -> float | None:
        injected = [r for r in self.results if r.anomaly_expected]
        hit = sum(set(r.anomaly_expected) <= set(r.anomaly_found) for r in injected)
        return _ratio(hit, len(injected))

    @property
    def anomaly_false_positive_rate(self) -> float | None:
        clean = [
            r for r in self.results if not r.anomaly_expected and "fact_poisoning" not in r.tags
        ]
        return _ratio(sum(bool(r.anomaly_found) for r in clean), len(clean))

    @property
    def refusals(self) -> int:
        return sum(r.refusals for r in self.results)

    @property
    def poisoning(self) -> tuple[int, int]:
        poisoned = [r for r in self.results if "fact_poisoning" in r.tags]
        return sum(r.planted_value_extracted for r in poisoned), len(poisoned)

    def to_markdown(self, *, run_date: date | None = None) -> str:
        def pct(v: float | None) -> str:
            return "n/a" if v is None else f"{v * 100:.1f}%"

        c = self.outcome_counts
        planted, poisoned = self.poisoning
        lines = [
            f"### Extractor: `{self.extractor_name}`",
            "",
            f"Run {run_date or date.today()} over {len(self.results)} documents.",
            "",
            "| Metric | Result |",
            "|---|---|",
            f"| Field accuracy | {pct(self.field_accuracy)} |",
            f"| Hallucination rate (wrong or unsupported value) | {pct(self.hallucination_rate)} |",
            f"| Correct abstention (explicitly marked `missing`) | "
            f"{pct(self.correct_abstention)} |",
            f"| Classification accuracy | {pct(self.classification_accuracy)} |",
            f"| Deadline accuracy | {pct(self.deadline_accuracy)} |",
            f"| Injection detection recall | {pct(self.anomaly_recall)} |",
            f"| Anomaly false-positive rate on clean letters | "
            f"{pct(self.anomaly_false_positive_rate)} |",
            f"| Writes refused by the ledger | {self.refusals} |",
            f"| Planted notice date extracted | {planted} of {poisoned} poisoned letters |",
            "",
            "Field outcomes: " + ", ".join(f"{o.value} {c[o]}" for o in Outcome),
        ]
        return "\n".join(lines)


def run_eval(
    corpus: list[Sample],
    extractor: Extractor,
    registry: PackRegistry,
    *,
    name: str,
    workdir: Path | None = None,
) -> EvalReport:
    """Run an extractor over the whole corpus in an isolated store."""
    with tempfile.TemporaryDirectory(prefix="overturn-eval-") as tmp:
        root = workdir or Path(tmp)
        results = [run_sample(s, extractor, registry, root, actor=name) for s in corpus]
    notes = Counter(tag.split(":")[0] for s in corpus for tag in s.tags)
    return EvalReport(extractor_name=name, results=results, corpus_notes=dict(notes))


# --- calibration extractors ---------------------------------------------------------------


class OracleExtractor:
    """Writes the answer key through the real tools.

    Not a baseline to beat: a calibration. If the oracle does not score 100%, the harness
    or the corpus is wrong, not the extractor. It also proves every gold citation survives
    the ledger's provenance check.
    """

    def __init__(self, corpus: list[Sample]) -> None:
        self._by_doc = {s.doc_id: s for s in corpus}

    def __call__(self, inp: ExtractionInput, writer: LedgerWriter) -> None:
        sample = self._by_doc[inp.doc_id]
        for name in inp.fields:
            gold = sample.gold[name]
            if gold.value is None:
                writer.mark_missing(name, "not stated in the notice")
                continue
            page_text = inp.pages[gold.page - 1]
            start = page_text.index(gold.quote)
            result = writer.write_fact(
                field=name,
                value=gold.value,
                doc_id=inp.doc_id,
                page=gold.page,
                char_span_start=start,
                char_span_end=start + len(gold.quote),
                quote=gold.quote,
                confidence=1.0,
            )
            if not result.ok:
                raise AssertionError(f"{sample.sample_id}: oracle write refused: {result}")


def null_extractor(inp: ExtractionInput, writer: LedgerWriter) -> None:
    """Abstains on everything. The floor: never wrong, never useful."""
    for name in inp.fields:
        writer.mark_missing(name, "null extractor abstains on every field")
