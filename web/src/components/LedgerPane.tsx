import { useState } from "react";
import type { Fact } from "../api";
import { fieldLabel, groupOf, valueText } from "../format";

interface Props {
  ledger: Fact[];
  active: string | null;
  onHover: (key: string | null) => void;
  onConfirm: (field: string) => void;
  onState: (field: string, value: unknown) => void;
  busy: boolean;
}

// The right half of the split view. A value is shown with the words it came from; an
// unknown value is shown as an empty box that says why. Nothing here is ever filled in
// to look complete.
export function LedgerPane({ ledger, active, onHover, onConfirm, onState, busy }: Props) {
  const groups = new Map<string, Fact[]>();
  for (const fact of ledger) {
    const g = groupOf(fact.field);
    groups.set(g, [...(groups.get(g) ?? []), fact]);
  }

  return (
    <div className="ledger">
      {[...groups.entries()].map(([group, facts]) => (
        <section key={group}>
          <h3>{group}</h3>
          {facts.map((f) => (
            <FactRow
              key={f.field}
              fact={f}
              active={active}
              onHover={onHover}
              onConfirm={onConfirm}
              onState={onState}
              busy={busy}
            />
          ))}
        </section>
      ))}
    </div>
  );
}

function FactRow({
  fact,
  active,
  onHover,
  onConfirm,
  onState,
  busy,
}: {
  fact: Fact;
  active: string | null;
  onHover: (key: string | null) => void;
  onConfirm: (field: string) => void;
  onState: (field: string, value: unknown) => void;
  busy: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const sourced = fact.provenance !== null;
  const canState =
    fact.origin !== "engine" &&
    (fact.status === "missing" ||
      fact.status === "extracted" ||
      (fact.status === "not_looked_for" && fact.required));

  return (
    <div
      className={`fact s-${fact.status} ${active === fact.field ? "active" : ""}`}
      onMouseEnter={() => sourced && onHover(fact.field)}
      onMouseLeave={() => sourced && onHover(null)}
    >
      <div className="fact-head">
        <span className="fact-label">
          {fieldLabel(fact.field)}
          {fact.critical && <span className="crit" title="Changes the outcome. Checked by a person before a packet goes out.">critical</span>}
          {fact.required && <span className="req" title="Required by this denial category">required</span>}
        </span>
        <Status fact={fact} />
      </div>

      {fact.status === "conflicted" ? (
        <div className="conflict">
          {fact.conflict.map((side, i) => (
            <div
              key={i}
              className={`side ${active === `${fact.field}#${i}` ? "active" : ""}`}
              onMouseEnter={() => onHover(`${fact.field}#${i}`)}
              onMouseLeave={() => onHover(null)}
            >
              <span className="fact-value">{valueText({ kind: fact.kind, value: side.reads })}</span>
              {side.provenance && (
                <span className="source">
                  {side.provenance.doc_id} p.{side.provenance.page}
                  {side.provenance.quote && (
                    <>
                      {" "}· <q>{side.provenance.quote}</q>
                    </>
                  )}
                </span>
              )}
              <button
                className="quiet-btn"
                disabled={busy}
                onClick={() => onState(fact.field, side.reads)}
              >
                Proceed on this reading
              </button>
            </div>
          ))}
        </div>
      ) : fact.value === null ? (
        <div className="gap-box">
          <span>{fact.status === "not_looked_for" ? "not read yet" : "no source found"}</span>
          {fact.reason && fact.status !== "not_looked_for" && (
            <span className="gap-reason">{fact.reason}</span>
          )}
        </div>
      ) : (
        <>
          <div className="fact-value">{valueText(fact)}</div>
          {fact.provenance?.quote && (
            <div className="source">
              p.{fact.provenance.page} · <q>{fact.provenance.quote}</q>
            </div>
          )}
          {fact.status === "regime_default" && fact.regime && (
            <div className="source">statutory default · {fact.regime}</div>
          )}
        </>
      )}

      {!editing && (
        <div className="fact-actions">
          {fact.status === "extracted" && fact.critical && (
            <button disabled={busy} onClick={() => onConfirm(fact.field)}>
              Confirm against original
            </button>
          )}
          {canState && (
            <button className="quiet-btn" disabled={busy} onClick={() => setEditing(true)}>
              {fact.value === null ? "I know this" : "Correct"}
            </button>
          )}
        </div>
      )}
      {editing && (
        <ValueForm
          fact={fact}
          onCancel={() => setEditing(false)}
          onSubmit={(v) => {
            setEditing(false);
            onState(fact.field, v);
          }}
        />
      )}
    </div>
  );
}

function Status({ fact }: { fact: Fact }) {
  switch (fact.status) {
    case "human_verified":
      return <span className="status ok" title={`Checked against the original by ${fact.verified_by}`}>verified · {fact.verified_by}</span>;
    case "human_answered":
      return <span className="status ok" title="Stated by a person; no document on file says it">stated · {fact.verified_by}</span>;
    case "extracted":
      return <span className="status unverified" title="Read from the document, not yet checked by a person">read, unchecked</span>;
    case "conflicted":
      return <span className="status conflict-tag">sources disagree</span>;
    case "regime_default":
      return <span className="status">statutory default</span>;
    case "missing":
      return <span className="status gap">not in the documents</span>;
    default:
      return null;
  }
}

function ValueForm({
  fact,
  onSubmit,
  onCancel,
}: {
  fact: Fact;
  onSubmit: (v: unknown) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState<string>(
    fact.value === null ? "" : Array.isArray(fact.value) ? fact.value.join(", ") : String(fact.value),
  );
  return (
    <form
      className="value-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (fact.kind === "bool") onSubmit(value === "true");
        else if (value.trim()) onSubmit(value.trim());
      }}
    >
      {fact.kind === "bool" ? (
        <select value={value} onChange={(e) => setValue(e.target.value)}>
          <option value="">Choose…</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      ) : (
        <input
          autoFocus
          type={fact.kind === "date" ? "date" : "text"}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      )}
      <button type="submit" disabled={fact.kind === "bool" ? value === "" : !value.trim()}>
        Record
      </button>
      <button type="button" className="quiet-btn" onClick={onCancel}>
        Cancel
      </button>
      <span className="muted small">Recorded as stated by you, not read from a document.</span>
    </form>
  );
}
