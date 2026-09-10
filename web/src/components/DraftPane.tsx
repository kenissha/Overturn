import { useState } from "react";
import { api, type Case } from "../api";
import { fieldLabel } from "../format";

interface Props {
  data: Case;
  busy: boolean;
  onEvidence: (evidenceId: string) => void;
  onFiled: (date: string) => void;
}

// The appeal as the ledger entitles it to be written. Each paragraph shows the facts it
// rests on; each paragraph that could not be written says what is missing. The letter is
// assembled by the engine from the rule pack — no model wrote a sentence of it.
export function DraftPane({ data, busy, onEvidence, onFiled }: Props) {
  const [copied, setCopied] = useState(false);
  const [filedOn, setFiledOn] = useState("");
  const plan = data.plan;
  const readiness = data.readiness;

  if (!plan || !readiness) {
    return (
      <div className="draft pad">
        <p>No denial category is established yet, so there is no argument to draft.</p>
        <p className="muted">{data.classification.explanation}</p>
      </div>
    );
  }

  async function copy() {
    const { text } = await api.letter(data.case_id);
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const missingDocs = [...readiness.missing_blocking, ...readiness.missing_optional];
  const filed = ["SUBMITTED", "AWAITING_RESPONSE", "DECISION"].includes(data.state);

  return (
    <div className="draft">
      <div className="draft-letter">
        <div className="draft-banner">
          Draft — prepared for your review. Overturn does not send anything.
        </div>
        {plan.included.map((p) => (
          <div key={p.step_id} className={`para ${p.rests_on_unverified ? "unverified" : ""}`}>
            <p>{p.text}</p>
            <div className="cites">
              {p.citations.map((c) => (
                <span
                  key={c.field}
                  className={`cite s-${c.status}`}
                  title={c.provenance?.quote ? `“${c.provenance.quote}” — page ${c.provenance.page}` : "Stated by a person"}
                >
                  {fieldLabel(c.field)}
                </span>
              ))}
              {p.evidence.map((ev) => (
                <span key={ev} className="cite evidence">
                  encl. {ev.replace(/_/g, " ")}
                </span>
              ))}
              {p.rests_on_unverified && (
                <span className="unverified-note">rests on a critical fact nobody has checked yet</span>
              )}
            </div>
          </div>
        ))}
        {plan.omitted
          .filter((o) => o.is_gap)
          .map((o) => (
            <div key={o.step_id} className="para omitted">
              <p>Not written: {o.reason}</p>
            </div>
          ))}
      </div>

      <aside className="draft-side">
        <section>
          <h3>Packet</h3>
          <p className={readiness.packet_ready ? "ok-text" : ""}>{readiness.summary}</p>
          <button onClick={copy} disabled={busy}>
            {copied ? "Copied" : "Copy draft"}
          </button>
        </section>

        <section>
          <h3>Documents</h3>
          <ul className="docs">
            {readiness.present.map((i) => (
              <li key={i.id} className="present">
                {i.label}
              </li>
            ))}
            {missingDocs.map((i) => (
              <li key={i.id} className={i.blocking ? "missing blocking" : "missing"}>
                <span>
                  {i.label}
                  {i.human_only && <span className="muted small"> · only you can obtain this</span>}
                  {!i.blocking && <span className="muted small"> · strengthens, not required</span>}
                </span>
                <button className="quiet-btn" disabled={busy} onClick={() => onEvidence(i.id)}>
                  Mark on file
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h3>Filing</h3>
          {filed ? (
            <p>Recorded as filed.</p>
          ) : (
            <form
              className="value-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (filedOn) onFiled(filedOn);
              }}
            >
              <input type="date" value={filedOn} onChange={(e) => setFiledOn(e.target.value)} />
              <button type="submit" disabled={busy || !filedOn}>
                Record as filed
              </button>
              <span className="muted small">
                A record that you sent it. Starts the plan's response clock.
              </span>
            </form>
          )}
        </section>
      </aside>
    </div>
  );
}
