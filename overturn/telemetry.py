"""Tracing: one span per pipeline step, and never a value from a document.

Patient data is masked in logs and traces, which the project requires of itself. Spans
here carry identifiers, states, counts and field names — never a field's value, a quote, or document
text — so a trace can be shared with whoever runs the infrastructure without sharing a
member's file.

    OVERTURN_OTEL=console    print spans to standard output
    OVERTURN_OTEL=otlp       export to OTEL_EXPORTER_OTLP_ENDPOINT (needs the OTLP exporter)

Strands instruments the extraction agent itself — model calls, tool calls, token counts.
Setting up tracing through Strands puts those spans inside the pipeline step that made
them, so one trace shows a letter going from upload to escalation.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable, Mapping
from typing import Any

from opentelemetry import trace

tracer = trace.get_tracer("overturn")


def setup_from_env(env: Mapping[str, str] | None = None) -> str | None:
    """Configure an exporter if OVERTURN_OTEL asks for one. Returns the mode, or None."""
    mode = (env if env is not None else os.environ).get("OVERTURN_OTEL", "").strip().lower()
    if not mode:
        return None
    from strands.telemetry import StrandsTelemetry

    telemetry = StrandsTelemetry()
    if mode == "console":
        telemetry.setup_console_exporter()
    elif mode == "otlp":
        telemetry.setup_otlp_exporter()
    else:
        raise ValueError(f"Unknown OVERTURN_OTEL {mode!r}. Expected console or otlp.")
    return mode


def traced(name: str) -> Callable:
    """Wrap a pipeline method taking ``case_id`` first in a span named ``name``."""

    def decorate(method: Callable) -> Callable:
        @functools.wraps(method)
        def inner(self, case_id: str, *args: Any, **kwargs: Any):
            with tracer.start_as_current_span(name) as span:
                span.set_attribute("overturn.case_id", case_id)
                if args and isinstance(args[0], str) and args[0].startswith("doc_"):
                    span.set_attribute("overturn.doc_id", args[0])
                result = method(self, case_id, *args, **kwargs)
                _describe(span, result)
                return result

        return inner

    return decorate


def _describe(span: Any, result: Any) -> None:
    """Attach what the step produced, as identifiers and counts only."""
    case = getattr(result, "case", None)
    if case is not None:
        span.set_attribute("overturn.state", case.state.value)
        span.set_attribute("overturn.facts_recorded", len(case.facts))
    pack = getattr(result, "pack", None)
    if pack is not None:
        span.set_attribute("overturn.rule_pack", pack.qualified_name)
    escalations = getattr(result, "escalations", None)
    if escalations is not None:
        span.set_attribute("overturn.escalations", len(escalations))
        span.set_attribute(
            "overturn.escalation_triggers", sorted({int(e.trigger) for e in escalations})
        )
    doc_id = getattr(result, "doc_id", None)
    if isinstance(doc_id, str):
        span.set_attribute("overturn.doc_id", doc_id)
        span.set_attribute("overturn.doc_kind", getattr(result, "kind", ""))
