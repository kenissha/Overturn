"""Tracing: a span for every pipeline step, and no document value in any of them."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from overturn.engine.packs import PackRegistry
from overturn.eval.corpus import build_corpus
from overturn.eval.harness import OracleExtractor
from overturn.ledger.store import CaseStore
from overturn.pipeline import Pipeline
from overturn.telemetry import setup_from_env

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def capture_spans():
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider = trace.get_tracer_provider()
    provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
    yield


def test_every_step_of_a_file_is_a_span_and_none_carries_a_document_value(tmp_path):
    EXPORTER.clear()
    corpus = build_corpus()
    sample = next(s for s in corpus if s.is_clean and s.gold["patient.member_id"].value)
    pipeline = Pipeline(
        CaseStore(tmp_path),
        PackRegistry.from_directory(Path(__file__).resolve().parents[1] / "packs"),
        OracleExtractor(corpus),
    )
    case_id = pipeline.store.create().case_id
    pipeline.ingest(
        case_id,
        filename="l.txt",
        kind="denial_letter",
        raw_pages=sample.pages,
        doc_id=sample.doc_id,
    )
    pipeline.process(case_id, today=date(2026, 9, 10))

    spans = EXPORTER.get_finished_spans()
    names = {s.name for s in spans}
    assert {"overturn.ingest", "overturn.extract", "overturn.evaluate"} <= names

    evaluated = next(s for s in spans if s.name == "overturn.evaluate")
    assert evaluated.attributes["overturn.case_id"] == case_id
    assert "overturn.state" in evaluated.attributes

    every_value = " ".join(str(v) for s in spans for v in s.attributes.values())
    for name, gold in sample.gold.items():
        if gold.value and name != "service.cpt_codes":
            assert str(gold.value) not in every_value, f"{name} leaked into a span"


def test_tracing_is_off_unless_asked_for():
    assert setup_from_env({}) is None
    with pytest.raises(ValueError):
        setup_from_env({"OVERTURN_OTEL": "somewhere"})
