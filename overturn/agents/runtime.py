"""Amazon Bedrock AgentCore Runtime entrypoint: the untrusted zone, deployed on its own.

The runtime receives one document's text and the fields to handle, runs the extraction
agent against a throwaway ledger, and returns what the agent *proposed*: each fact with
its page and quote, and each field it marked missing.

That answer is not trusted either. The caller replays every proposal through its own
ledger writer (``overturn/agents/remote.py``), so each quote is located again, on the
caller's copy of the document, before anything reaches the real ledger. A compromised or
misconfigured runtime can propose anything; it can record nothing the local ledger cannot
verify. The trust boundary survives the network hop.

Deployed through the repository-root entrypoint ``agentcore_app.py``; see
deploy/agentcore/README.md.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from typing import Any

from overturn.extraction import DEFAULT_FIELDS, ExtractionInput, Extractor
from overturn.ledger.documents import DocumentText
from overturn.ledger.schema import Document, FactStatus
from overturn.ledger.store import CaseStore
from overturn.tools.ledger_tools import LedgerWriter

RUNTIME_ACTOR = "ExtractionAgent@agentcore"
MAX_PAGES = 50
"""A denial letter is a few pages. A payload far larger than that is refused, not read."""


class InvalidPayload(ValueError):
    """The invocation did not carry one document in the expected shape."""


def extract_document(payload: Mapping[str, Any], extractor: Extractor) -> dict[str, Any]:
    """Run an extractor over one document and return its proposals.

    Pure with respect to the outside world: everything the extractor writes goes into a
    temporary ledger that is discarded when this returns.
    """
    doc_id, pages, fields = _validate(payload)
    text = DocumentText.from_pages(doc_id, pages)

    with tempfile.TemporaryDirectory(prefix="overturn-runtime-") as tmp:
        store = CaseStore(tmp)
        case = store.create()
        case.documents.append(
            Document(
                doc_id=doc_id,
                kind="denial_letter",
                filename=doc_id,
                pages=max(1, len(pages)),
                sha256=text.sha256(),
            )
        )
        store.save(case)
        writer = LedgerWriter(store, case, actor=RUNTIME_ACTOR, texts={doc_id: text})
        extractor(ExtractionInput(doc_id=doc_id, pages=text.pages, fields=fields), writer)
        case = store.load(case.case_id)
        refused = sum(1 for e in store.read_audit(case.case_id) if e["outcome"] == "refused")

    facts, missing = [], []
    for name, fact in case.facts.items():
        if fact.status is FactStatus.MISSING:
            missing.append({"field": name, "reason": fact.reason})
        elif fact.provenance is not None:
            facts.append(
                {
                    "field": name,
                    "value": fact.value,
                    "page": fact.provenance.page,
                    "quote": fact.provenance.quote,
                    "confidence": fact.confidence,
                }
            )
    return {
        "doc_id": doc_id,
        "document_sha256": text.sha256(),
        "facts": facts,
        "missing": missing,
        "refused_in_runtime": refused,
    }


def _validate(payload: Mapping[str, Any]) -> tuple[str, list[str], tuple[str, ...]]:
    if not isinstance(payload, Mapping):
        raise InvalidPayload("payload must be a JSON object")
    doc_id = payload.get("doc_id")
    pages = payload.get("pages")
    if not isinstance(doc_id, str) or not doc_id:
        raise InvalidPayload("doc_id must be a non-empty string")
    if not isinstance(pages, list) or not all(isinstance(p, str) for p in pages):
        raise InvalidPayload("pages must be a list of strings")
    if not pages or len(pages) > MAX_PAGES:
        raise InvalidPayload(f"pages must hold between 1 and {MAX_PAGES} pages")
    fields = payload.get("fields") or DEFAULT_FIELDS
    if not isinstance(fields, list | tuple) or not all(isinstance(f, str) for f in fields):
        raise InvalidPayload("fields must be a list of field names")
    return doc_id, pages, tuple(fields)


def build_app():
    """The AgentCore application. Imported lazily so the rest of the package never needs
    the AgentCore SDK installed."""
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    from overturn.agents.extraction import StrandsExtractor
    from overturn.models.factory import build_model

    app = BedrockAgentCoreApp()
    extractor = StrandsExtractor(lambda: build_model("extraction"))

    @app.entrypoint
    def invoke(payload):
        try:
            return extract_document(payload, extractor)
        except InvalidPayload as exc:
            return {"error": str(exc)}

    return app


if __name__ == "__main__":
    build_app().run()
