import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Case, type DocumentText } from "../api";
import { DeadlineStrip } from "../components/DeadlineStrip";
import { DocumentPane, type SourceSpan } from "../components/DocumentPane";
import { DraftPane } from "../components/DraftPane";
import { Escalations } from "../components/Escalations";
import { LedgerPane } from "../components/LedgerPane";
import { TracePane } from "../components/TracePane";
import { STATE_LABEL } from "../format";

// Screen 2, the heart of the demo: the letter on the left, the ledger on the right, and
// the questions only a person can answer beside them.
export function CaseView({
  caseId,
  tab,
  extractor,
  today,
}: {
  caseId: string;
  tab: string;
  extractor: boolean;
  today: string;
}) {
  const [data, setData] = useState<Case | null>(null);
  const [texts, setTexts] = useState<Record<string, DocumentText>>({});
  const [docId, setDocId] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getCase(caseId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [caseId]);

  useEffect(() => {
    if (!data) return;
    for (const d of data.documents) {
      if (texts[d.doc_id]) continue;
      api.document(caseId, d.doc_id).then((t) => setTexts((prev) => ({ ...prev, [d.doc_id]: t })));
    }
    if (!docId && data.documents.length) setDocId(data.documents[0].doc_id);
  }, [data, caseId, docId, texts]);

  const act = useCallback(async (run: () => Promise<Case>) => {
    setBusy(true);
    setError(null);
    try {
      setData(await run());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const spans = useMemo<SourceSpan[]>(() => {
    if (!data) return [];
    const out: SourceSpan[] = [];
    for (const f of data.ledger) {
      if (f.provenance) {
        const [start, end] = f.provenance.char_span;
        out.push({ key: f.field, doc_id: f.provenance.doc_id, page: f.provenance.page, start, end });
      }
      f.conflict.forEach((side, i) => {
        if (!side.provenance) return;
        const [start, end] = side.provenance.char_span;
        out.push({ key: `${f.field}#${i}`, doc_id: side.provenance.doc_id, page: side.provenance.page, start, end });
      });
    }
    return out;
  }, [data]);

  // Hovering a fact on another document brings that document forward.
  const hover = useCallback(
    (key: string | null) => {
      setActive(key);
      if (!key) return;
      const span = spans.find((s) => s.key === key);
      if (span && span.doc_id !== docId) setDocId(span.doc_id);
    },
    [spans, docId],
  );

  if (error && !data) return <p className="error">Could not open this file: {error}</p>;
  if (!data) return <p className="muted pad">Loading…</p>;

  const service = data.ledger.find((f) => f.field === "service.description")?.value as string | undefined;
  const issuer = data.ledger.find((f) => f.field === "plan.issuer")?.value as string | undefined;
  const unread = data.state === "INTAKE" && data.ledger.every((f) => f.status === "not_looked_for");
  const current = docId ? texts[docId] : undefined;

  return (
    <div className="case">
      <div className="case-head">
        <div>
          <a href="#/" className="back">
            ← Today
          </a>
          <h1>{service ?? "Unread letter"}</h1>
          <p className="muted">
            {issuer ?? "Insurer not yet read"} · {data.pack ? data.pack.name : "Category not established"}
          </p>
        </div>
        <div className="case-head-right">
          <span className={`state st-${data.state}`}>{STATE_LABEL[data.state] ?? data.state}</span>
          {unread && extractor && (
            <button disabled={busy} onClick={() => act(async () => (await api.process(caseId)).case)}>
              Read the letter
            </button>
          )}
        </div>
      </div>

      <DeadlineStrip deadlines={data.deadlines} today={today} />

      <nav className="tabs">
        <a href={`#/case/${caseId}`} className={tab === "ledger" ? "on" : ""}>
          Letter and ledger
        </a>
        <a href={`#/case/${caseId}/draft`} className={tab === "draft" ? "on" : ""}>
          Draft appeal
        </a>
        <a href={`#/case/${caseId}/trace`} className={tab === "trace" ? "on" : ""}>
          Trace
        </a>
      </nav>

      {error && <p className="error">{error}</p>}

      {tab === "draft" ? (
        <DraftPane
          data={data}
          busy={busy}
          onEvidence={(id) => act(() => api.attachEvidence(caseId, id))}
          onFiled={(d) => act(() => api.markFiled(caseId, d))}
          onDecision={(outcome, d) => act(() => api.decision(caseId, outcome, d))}
        />
      ) : tab === "trace" ? (
        <TracePane data={data} />
      ) : (
        <div className="split">
          <div className="pane pane-doc">
            <div className="doc-tabs">
              {data.documents.length > 1 &&
                data.documents.map((d) => (
                  <button
                    key={d.doc_id}
                    className={d.doc_id === docId ? "on" : "quiet-btn"}
                    onClick={() => setDocId(d.doc_id)}
                  >
                    {d.filename}
                  </button>
                ))}
              <AddDocument
                busy={busy}
                onAdd={(file, kind) =>
                  act(async () => {
                    await api.upload(caseId, file, kind);
                    return (await api.process(caseId)).case;
                  })
                }
              />
            </div>
            {current ? (
              <DocumentPane document={current} spans={spans} active={active} onHover={hover} />
            ) : (
              <p className="muted pad">{data.documents.length ? "Loading the letter…" : "No documents on this file yet."}</p>
            )}
          </div>
          <div className="pane pane-ledger">
            <LedgerPane
              ledger={data.ledger}
              active={active}
              onHover={hover}
              busy={busy}
              onConfirm={(field) => act(() => api.confirm(caseId, field))}
              onState={(field, value) => act(() => api.stateFact(caseId, field, value))}
            />
          </div>
          <Escalations
            escalations={data.escalations}
            silent={data.silent}
            ledger={data.ledger}
            busy={busy}
            onFocus={hover}
            onAnswer={(id, answer) => act(() => api.answer(caseId, id, answer))}
            onCorrect={(field, value) => act(() => api.stateFact(caseId, field, value))}
          />
        </div>
      )}
    </div>
  );
}

const DOCUMENT_KINDS: [string, string][] = [
  ["plan_document", "Plan document (read for what it covers)"],
  ["denial_letter", "Another denial letter"],
  ["supporting", "Supporting record (kept on file, not read)"],
];

// A second source is how contradictions surface: a plan document that covers what the
// denial calls excluded is recorded as a conflict with both quotes, never silently resolved.
function AddDocument({ busy, onAdd }: { busy: boolean; onAdd: (file: File, kind: string) => void }) {
  const [kind, setKind] = useState(DOCUMENT_KINDS[0][0]);
  return (
    <label className="add-doc">
      <select value={kind} disabled={busy} onChange={(e) => setKind(e.target.value)}>
        {DOCUMENT_KINDS.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <span className="quiet-btn">Add a document</span>
      <input
        type="file"
        accept=".pdf,.txt"
        hidden
        disabled={busy}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onAdd(file, kind);
          e.target.value = "";
        }}
      />
    </label>
  );
}
