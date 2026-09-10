"""Calling the extraction agent on Amazon Bedrock AgentCore — without trusting its answer.

``AgentCoreExtractor`` implements the ordinary extractor contract. It sends one document to
the deployed runtime, receives the facts the agent proposed, and replays every proposal
through the local ledger writer:

- The runtime reports a hash of the text it read. If that does not match the local copy,
  nothing is replayed: the runtime read a different document.
- Every proposed fact goes through ``write_fact_by_quote``, so its quote is located again on
  the local page text and its field is checked against the local taxonomy and write
  origins. A proposal the local ledger cannot verify is refused and audited here.
- Only fields that were asked for are replayed.

A compromised or misconfigured runtime can propose anything. It can record nothing the
local ledger would not have accepted from a local agent.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from overturn.extraction import ExtractionInput
from overturn.tools.ledger_tools import LedgerWriter

Invoker = Callable[[dict[str, Any]], dict[str, Any]]
"""Sends one payload to the runtime and returns its decoded JSON response."""


class RemoteExtractionError(RuntimeError):
    """The runtime's answer could not be used at all."""


def agentcore_invoker(
    runtime_arn: str, *, region: str | None = None, qualifier: str = "DEFAULT"
) -> Invoker:
    """An invoker backed by the AgentCore data plane. One session per document."""
    import boto3

    client = boto3.client("bedrock-agentcore", region_name=region)

    def invoke(payload: dict[str, Any]) -> dict[str, Any]:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            qualifier=qualifier,
            runtimeSessionId=f"overturn-document-{uuid.uuid4().hex}",
            contentType="application/json",
            accept="application/json",
            payload=json.dumps(payload).encode("utf-8"),
        )
        return json.loads(response["response"].read())

    return invoke


class AgentCoreExtractor:
    def __init__(self, invoke: Invoker) -> None:
        self._invoke = invoke
        self.last_ignored: list[str] = []
        """Proposed fields that were not asked for, from the most recent document."""

    def __call__(self, inp: ExtractionInput, writer: LedgerWriter) -> None:
        local = writer.texts[inp.doc_id]
        result = self._invoke(
            {"doc_id": inp.doc_id, "pages": list(inp.pages), "fields": list(inp.fields)}
        )
        if not isinstance(result, dict):
            raise RemoteExtractionError("The runtime returned something other than an object.")
        if "error" in result:
            raise RemoteExtractionError(f"The runtime refused the document: {result['error']}")
        if result.get("document_sha256") != local.sha256():
            raise RemoteExtractionError(
                "The runtime read a different text than the one on this case. None of its "
                "proposals were recorded."
            )

        asked = set(inp.fields)
        self.last_ignored = []
        for proposal in result.get("facts") or []:
            field = str(proposal.get("field", ""))
            if field not in asked:
                self.last_ignored.append(field)
                continue
            writer.write_fact_by_quote(
                field,
                proposal.get("value"),
                inp.doc_id,
                _as_int(proposal.get("page")),
                str(proposal.get("quote") or ""),
                _as_confidence(proposal.get("confidence")),
            )
        for absent in result.get("missing") or []:
            field = str(absent.get("field", ""))
            if field not in asked:
                self.last_ignored.append(field)
                continue
            writer.mark_missing(field, str(absent.get("reason") or "not stated in the document"))


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0  # page 0 does not exist, so the local writer refuses the proposal


def _as_confidence(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
