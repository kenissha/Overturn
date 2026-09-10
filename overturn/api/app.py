"""The HTTP API behind the advocate's interface.

Thin by design. Every route either hands a person's action to the pipeline or returns a
view of what the deterministic layer computed; no route decides anything. There is no
endpoint that submits an appeal, sends a message or notifies anyone — those capabilities
do not exist in this codebase, so they cannot be exposed by accident.

Run locally:

    uvicorn --factory overturn.api.app:app_from_env --reload

``OVERTURN_EXTRACTOR=model`` enables the extraction agent (and a paid model call per
denial letter). Without it, documents are stored and scanned but not read for facts.

``OVERTURN_TODAY=YYYY-MM-DD`` pins the clock for a demonstration. The interface labels a
pinned clock rather than presenting it as the real date.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from overturn.api.views import case_summary, queue_order, snapshot_view
from overturn.engine.argument import render_letter
from overturn.engine.packs import PackRegistry
from overturn.extraction import Extractor
from overturn.ledger.errors import LedgerError
from overturn.ledger.store import CaseStore
from overturn.pipeline import CaseSnapshot, Pipeline

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_USER = "advocate"
QUEUE_CARDS = 3
"""The morning queue shows this many cases. Everything else is 'progressing in the
background' — counted, reachable, and deliberately not in the way."""


class TextDocument(BaseModel):
    filename: str
    kind: str = "denial_letter"
    pages: list[str]


class AnswerBody(BaseModel):
    answer: str


class FactBody(BaseModel):
    value: Any


class FiledBody(BaseModel):
    filed_on: date


def create_app(
    *,
    data_dir: str | Path,
    packs_dir: str | Path = ROOT / "packs",
    extractor: Extractor | None = None,
    today: Callable[[], date] | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    store = CaseStore(data_dir)
    pipeline = Pipeline(store, PackRegistry.from_directory(packs_dir), extractor)
    clock = today or date.today

    app = FastAPI(title="Overturn", version="0.1.0")
    app.state.pipeline = pipeline
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def snapshot(case_id: str) -> CaseSnapshot:
        try:
            return pipeline.evaluate(case_id, today=clock())
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, f"No such case: {case_id}") from exc

    def view(s: CaseSnapshot) -> dict[str, Any]:
        return snapshot_view(s, clock())

    # -- overview --------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "extractor": extractor is not None,
            "packs": pipeline.registry.ids,
            "today": clock().isoformat(),
            "fixed_clock": today is not None,
        }

    @app.get("/api/queue")
    def queue() -> dict[str, Any]:
        """The morning view: what needs a person today, and how much is running quietly."""
        summaries = [case_summary(snapshot(cid), clock()) for cid in store.list_case_ids()]
        attention = sorted((s for s in summaries if s["escalation_count"]), key=queue_order)
        return {
            "today": clock().isoformat(),
            "attention": attention[:QUEUE_CARDS],
            "attention_total": len(attention),
            "quiet_count": len(summaries) - len(attention),
        }

    @app.get("/api/cases")
    def list_cases() -> list[dict[str, Any]]:
        summaries = [case_summary(snapshot(cid), clock()) for cid in store.list_case_ids()]
        return sorted(summaries, key=queue_order)

    @app.post("/api/cases", status_code=201)
    def create_case() -> dict[str, Any]:
        return view(pipeline.evaluate(store.create().case_id, today=clock()))

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str) -> dict[str, Any]:
        return view(snapshot(case_id))

    # -- documents ---------------------------------------------------------------------

    @app.post("/api/cases/{case_id}/documents/text", status_code=201)
    def add_text_document(case_id: str, body: TextDocument) -> dict[str, Any]:
        snapshot(case_id)
        document = pipeline.ingest(
            case_id, filename=body.filename, kind=body.kind, raw_pages=body.pages
        )
        return {"doc_id": document.doc_id, "case": view(snapshot(case_id))}

    @app.post("/api/cases/{case_id}/documents", status_code=201)
    async def upload_document(
        case_id: str,
        file: Annotated[UploadFile, File()],
        kind: Annotated[str, Form()] = "denial_letter",
    ) -> dict[str, Any]:
        snapshot(case_id)
        raw = await file.read()
        pages = _pages_from_upload(file.filename or "document", raw)
        document = pipeline.ingest(
            case_id, filename=file.filename or "document", kind=kind, raw_pages=pages
        )
        return {"doc_id": document.doc_id, "case": view(snapshot(case_id))}

    @app.get("/api/cases/{case_id}/documents/{doc_id}")
    def get_document(case_id: str, doc_id: str) -> dict[str, Any]:
        """Normalised page text: the exact string every provenance span indexes into."""
        snapshot(case_id)
        try:
            data = store.load_document_text(case_id, doc_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, f"No such document: {doc_id}") from exc
        return {"doc_id": doc_id, "pages": data["pages"], "anomalies": data["anomalies"]}

    @app.post("/api/cases/{case_id}/process")
    def process(case_id: str) -> dict[str, Any]:
        snapshot(case_id)
        read = pipeline.extract_pending(case_id) if extractor is not None else 0
        return {
            "documents_read": read,
            "extractor": extractor is not None,
            "case": view(snapshot(case_id)),
        }

    # -- a person acts -------------------------------------------------------------------

    @app.post("/api/cases/{case_id}/escalations/{esc_id}/answer")
    def answer(
        case_id: str,
        esc_id: str,
        body: AnswerBody,
        x_overturn_user: str = Header(DEFAULT_USER),
    ) -> dict[str, Any]:
        snapshot(case_id)
        try:
            return view(
                pipeline.answer(case_id, esc_id, body.answer, by=x_overturn_user, today=clock())
            )
        except KeyError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/cases/{case_id}/facts/{field}/confirm")
    def confirm(
        case_id: str, field: str, x_overturn_user: str = Header(DEFAULT_USER)
    ) -> dict[str, Any]:
        snapshot(case_id)
        try:
            return view(pipeline.confirm_fact(case_id, field, by=x_overturn_user, today=clock()))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.put("/api/cases/{case_id}/facts/{field}")
    def state_fact(
        case_id: str, field: str, body: FactBody, x_overturn_user: str = Header(DEFAULT_USER)
    ) -> dict[str, Any]:
        snapshot(case_id)
        try:
            return view(
                pipeline.state_fact(case_id, field, body.value, by=x_overturn_user, today=clock())
            )
        except LedgerError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/cases/{case_id}/evidence/{evidence_id}")
    def attach_evidence(
        case_id: str, evidence_id: str, x_overturn_user: str = Header(DEFAULT_USER)
    ) -> dict[str, Any]:
        snapshot(case_id)
        return view(
            pipeline.attach_evidence(case_id, evidence_id, by=x_overturn_user, today=clock())
        )

    @app.post("/api/cases/{case_id}/filed")
    def mark_filed(
        case_id: str, body: FiledBody, x_overturn_user: str = Header(DEFAULT_USER)
    ) -> dict[str, Any]:
        """Record that a person filed the appeal. This is a record, not a submission."""
        snapshot(case_id)
        try:
            return view(
                pipeline.mark_filed(case_id, body.filed_on, by=x_overturn_user, today=clock())
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    # -- outputs -------------------------------------------------------------------------

    @app.get("/api/cases/{case_id}/letter")
    def letter(case_id: str) -> dict[str, Any]:
        s = snapshot(case_id)
        if s.plan is None:
            raise HTTPException(
                409, "No denial category is established yet, so there is no argument to draft."
            )
        return {"text": render_letter(s.plan, s.case), "gaps": len(s.plan.gaps)}

    @app.get("/api/cases/{case_id}/audit")
    def audit(case_id: str) -> list[dict[str, Any]]:
        snapshot(case_id)
        return store.read_audit(case_id)

    return app


def _pages_from_upload(filename: str, raw: bytes) -> list[str]:
    """Text files split on form feeds; PDFs page by page. Scanned images are out of scope."""
    if filename.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - dependency declared in the api extra
            raise HTTPException(415, "PDF support requires the 'pypdf' package.") from exc
        reader = PdfReader(io.BytesIO(raw))
        pages = [(page.extract_text() or "") for page in reader.pages]
        if not any(p.strip() for p in pages):
            raise HTTPException(
                422,
                "This PDF has no text layer. Scanned documents need OCR, which is outside what "
                "this version reads.",
            )
        return pages
    text = raw.decode("utf-8", errors="replace")
    pages = [p for p in text.split("\f")] or [text]
    return pages


def app_from_env() -> FastAPI:
    """Application factory for uvicorn, configured from the environment."""
    extractor: Extractor | None = None
    if os.environ.get("OVERTURN_EXTRACTOR") == "model":
        from overturn.agents.extraction import StrandsExtractor
        from overturn.models.factory import build_model

        extractor = StrandsExtractor(lambda: build_model("extraction"))

    fixed = os.environ.get("OVERTURN_TODAY")
    clock = (lambda: date.fromisoformat(fixed)) if fixed else None

    origins = os.environ.get("OVERTURN_CORS")
    return create_app(
        data_dir=os.environ.get("OVERTURN_DATA_DIR", ROOT / "data"),
        extractor=extractor,
        today=clock,
        cors_origins=origins.split(",") if origins else None,
    )
