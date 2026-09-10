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

// The left half of the split view: the letter exactly as the engine read it. Every
// highlight is a character span a ledger fact points at, so what lights up is precisely
// the text that justifies the value on the right — nothing inferred, nothing approximate.
export function DocumentPane({ document, spans, active, onHover }: Props) {
  const activeRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [active]);

  const pages = useMemo(
    () =>
      document.pages.map((text, i) => {
        const page = i + 1;
        const marks: Mark[] = [
          ...spans
            .filter((s) => s.doc_id === document.doc_id && s.page === page)
            .map((s) => ({ start: s.start, end: s.end, key: s.key })),
          ...document.anomalies
            .filter((a) => a.page === page && a.char_span)
            .map((a) => ({ start: a.char_span![0], end: a.char_span![1], anomaly: a })),
        ];
        return { page, segments: segment(text, marks) };
      }),
    [document, spans],
  );

  const hidden = document.anomalies.filter((a) => a.kind === "hidden_text");
  let firstActiveSeen = false;

  return (
    <div className="document">
      {hidden.map((a, i) => (
        <div key={i} className="anomaly-banner">
          <strong>Hidden text removed from page {a.page}.</strong> {a.excerpt}. {a.explanation}
        </div>
      ))}
      {pages.map(({ page, segments }) => (
        <section key={page} className="page">
          <div className="page-label">Page {page}</div>
          <pre className="page-text">
            {segments.map((seg, j) => {
              if (!seg.keys.length && !seg.anomaly) return <span key={j}>{seg.text}</span>;
              const isActive = active !== null && seg.keys.includes(active);
              const setRef = isActive && !firstActiveSeen;
              if (setRef) firstActiveSeen = true;
              const cls = [
                seg.keys.length ? "src" : "",
                isActive ? "active" : "",
                seg.anomaly ? `anomaly sev-${seg.anomaly.severity}` : "",
              ].join(" ");
              return (
                <mark
                  key={j}
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
