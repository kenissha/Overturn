import { useEffect, useMemo, useRef } from "react";
import type { Anomaly, DocumentText } from "../api";

export interface SourceSpan {
  key: string; // a ledger field, or field#n for one side of a conflict
  doc_id: string;
  page: number;
  start: number;
  end: number;
}

interface Props {
  document: DocumentText;
  spans: SourceSpan[];
  active: string | null;
  onHover: (key: string | null) => void;
}

interface Mark {
  start: number;
  end: number;
  key?: string;
  anomaly?: Anomaly;
}

const ANOMALY_TITLE: Record<string, string> = {
  instruction_pattern: "Text addressed to an automated reader",
  role_impersonation: "Text imitating a system message",
  suppression_request: "A request to keep something from you",
  hidden_text: "Hidden characters removed",
  low_ocr_confidence: "Poorly scanned document",
};

const anomalyId = (a: Anomaly) => `anomaly-${a.doc_id}-${a.page ?? 0}-${a.char_span?.[0] ?? 0}`;

// The left half of the split view: the letter exactly as the engine read it. Every
// highlight is a character span a ledger fact points at, so what lights up is precisely
// the text that justifies the value on the right — nothing inferred, nothing approximate.
// Anything anomalous is announced at the top and marked where it sits on the page.
export function DocumentPane({ document: doc, spans, active, onHover }: Props) {
  const activeRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [active]);

  const pages = useMemo(
    () =>
      doc.pages.map((text, i) => {
        const page = i + 1;
        const marks: Mark[] = [
          ...spans
            .filter((s) => s.doc_id === doc.doc_id && s.page === page)
            .map((s) => ({ start: s.start, end: s.end, key: s.key })),
          ...doc.anomalies
            .filter((a) => a.page === page && a.char_span)
            .map((a) => ({ start: a.char_span![0], end: a.char_span![1], anomaly: a })),
        ];
        return { page, segments: segment(text, marks) };
      }),
    [doc, spans],
  );

  let firstActiveSeen = false;
  const anchored = new Set<string>();

  return (
    <div className="document">
      {doc.anomalies.length > 0 && (
        <div className="anomalies">
          {doc.anomalies.map((a, i) => (
            <div key={i} className={`anomaly-banner sev-${a.severity}`}>
              <div>
                <strong>{ANOMALY_TITLE[a.kind] ?? "Unexpected content"}</strong>
                {a.page ? ` · page ${a.page}` : ""}
              </div>
              <div className="small">{a.explanation} Nothing acted on it.</div>
              {a.char_span ? (
                <button
                  className="quiet-btn"
                  onClick={() =>
                    document
                      .getElementById(anomalyId(a))
                      ?.scrollIntoView({ block: "center", behavior: "smooth" })
                  }
                >
                  Show it on the page
                </button>
              ) : (
                <div className="mono small muted">{a.excerpt}</div>
              )}
            </div>
          ))}
        </div>
      )}
      {pages.map(({ page, segments }) => (
        <section key={page} className="page">
          <div className="page-label">Page {page}</div>
          <pre className="page-text">
            {segments.map((seg, j) => {
              if (!seg.keys.length && !seg.anomaly) return <span key={j}>{seg.text}</span>;
              const isActive = active !== null && seg.keys.includes(active);
              const setRef = isActive && !firstActiveSeen;
              if (setRef) firstActiveSeen = true;
              const aid = seg.anomaly ? anomalyId(seg.anomaly) : undefined;
              const giveId = aid !== undefined && !anchored.has(aid);
              if (giveId) anchored.add(aid);
              const cls = [
                seg.keys.length ? "src" : "",
                isActive ? "active" : "",
                seg.anomaly ? `anomaly sev-${seg.anomaly.severity}` : "",
              ].join(" ");
              return (
                <mark
                  key={j}
                  id={giveId ? aid : undefined}
                  ref={setRef ? (el) => void (activeRef.current = el) : undefined}
                  className={cls}
                  title={seg.anomaly ? seg.anomaly.explanation : undefined}
                  onMouseEnter={() => seg.keys.length && onHover(seg.keys[0])}
                  onMouseLeave={() => seg.keys.length && onHover(null)}
                >
                  {seg.text}
                </mark>
              );
            })}
          </pre>
        </section>
      ))}
    </div>
  );
}

function segment(text: string, marks: Mark[]) {
  const clamp = (n: number) => Math.max(0, Math.min(text.length, n));
  const points = new Set<number>([0, text.length]);
  for (const m of marks) {
    points.add(clamp(m.start));
    points.add(clamp(m.end));
  }
  const cuts = [...points].sort((a, b) => a - b);
  const out: { text: string; keys: string[]; anomaly?: Anomaly }[] = [];
  for (let i = 0; i < cuts.length - 1; i++) {
    const [a, b] = [cuts[i], cuts[i + 1]];
    if (a === b) continue;
    const covering = marks.filter((m) => clamp(m.start) <= a && clamp(m.end) >= b);
    out.push({
      text: text.slice(a, b),
      keys: covering.flatMap((m) => (m.key ? [m.key] : [])),
      anomaly: covering.find((m) => m.anomaly)?.anomaly,
    });
  }
  return out;
}
