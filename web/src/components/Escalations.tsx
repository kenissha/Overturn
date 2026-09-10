import { useState } from "react";
import type { Escalation, Fact } from "../api";
import { TRIGGER_LABEL } from "../format";

interface Props {
  escalations: Escalation[];
  silent: string[];
  ledger: Fact[];
  busy: boolean;
  onAnswer: (escalationId: string, answer: string) => void;
  onCorrect: (field: string, value: unknown) => void;
  onFocus: (field: string | null) => void;
}

// What to read first. A tampered document changes how everything else on the file should
// be read, and a clock can end the file; the rest can wait a few seconds longer.
const READING_ORDER: Record<number, number> = { 4: 0, 3: 1, 1: 2, 2: 3 };

// Screen 4. The only place the system speaks to the advocate, and only for one of four
// reasons. Every question says why it is worth their attention. There is no chat: the
// agent asks, the person answers, and the answer lands in the ledger.
export function Escalations({ escalations, silent, ledger, busy, onAnswer, onCorrect, onFocus }: Props) {
  const ordered = [...escalations].sort(
    (a, b) =>
      READING_ORDER[a.trigger] - READING_ORDER[b.trigger] || Number(b.blocking) - Number(a.blocking),
  );

  return (
    <aside className="escalations">
      <h2>
        Needs you <span className="count">{escalations.length}</span>
      </h2>
      {escalations.length === 0 && <p className="muted">Nothing on this file needs you right now.</p>}
      {ordered.map((e) => (
        <EscalationCard
          key={e.id}
          escalation={e}
          fact={ledger.find((f) => f.field === e.subject)}
          busy={busy}
          onAnswer={onAnswer}
          onCorrect={onCorrect}
          onFocus={onFocus}
        />
      ))}
      {silent.length > 0 && (
        <details className="silent">
          <summary>{silent.length} noted without interrupting you</summary>
          <ul>
            {silent.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </details>
      )}
    </aside>
  );
}

function EscalationCard({
  escalation: e,
  fact,
  busy,
  onAnswer,
  onCorrect,
  onFocus,
}: {
  escalation: Escalation;
  fact: Fact | undefined;
  busy: boolean;
  onAnswer: (id: string, answer: string) => void;
  onCorrect: (field: string, value: unknown) => void;
  onFocus: (field: string | null) => void;
}) {
  const [correcting, setCorrecting] = useState(false);
  const [value, setValue] = useState("");

  return (
    <div
      className={`esc t${e.trigger} ${e.blocking ? "blocking" : ""}`}
      onMouseEnter={() => fact?.provenance && onFocus(fact.field)}
      onMouseLeave={() => fact?.provenance && onFocus(null)}
    >
      <span className={`chip t${e.trigger}`}>
        {TRIGGER_LABEL[e.trigger]}
        {e.blocking && " · blocks the packet"}
      </span>
      <p className="esc-question">{e.question}</p>
      <p className="esc-why">
        <span className="why-label">Why this matters</span> {e.why_it_matters}
      </p>
      {e.detail && <p className="esc-detail">{e.detail}</p>}

      {correcting && fact ? (
        <form
          className="value-form"
          onSubmit={(ev) => {
            ev.preventDefault();
            if (value.trim()) onCorrect(fact.field, value.trim());
          }}
        >
          <input
            autoFocus
            type={fact.kind === "date" ? "date" : "text"}
            value={value}
            onChange={(ev) => setValue(ev.target.value)}
          />
          <button type="submit" disabled={busy || !value.trim()}>
            Record correction
          </button>
          <button type="button" className="quiet-btn" onClick={() => setCorrecting(false)}>
            Cancel
          </button>
        </form>
      ) : (
        <div className="options">
          {e.options.map((option) =>
            option === "Correct it" ? (
              <button key={option} className="quiet-btn" disabled={busy} onClick={() => setCorrecting(true)}>
                Correct it
              </button>
            ) : (
              <button key={option} disabled={busy} onClick={() => onAnswer(e.id, option)}>
                {option}
              </button>
            ),
          )}
          {e.options.length === 0 && <span className="muted small">Resolve this in the ledger.</span>}
        </div>
      )}
    </div>
  );
}
