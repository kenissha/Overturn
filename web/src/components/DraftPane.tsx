import { useState } from "react";
import { api, type Case } from "../api";
import { fieldLabel, STATE_LABEL } from "../format";

interface Props {
  data: Case;
  busy: boolean;
  onEvidence: (evidenceId: string) => void;
  onFiled: (date: string) => void;
  onDecision: (outcome: "overturned" | "upheld", decidedOn: string) => void;
}

const AWAITING_DECISION = ["SUBMITTED", "AWAITING_RESPONSE", "DECISION", "EXTERNAL_REVIEW"];
const FINISHED = ["RESOLVED_OVERTURNED", "RESOLVED_UPHELD", "CLOSED_DEADLINE_MISSED"];

// The appeal as the ledger entitles it to be written. Each paragraph shows the facts it
// rests on; each paragraph that could not be written says what is missing. The letter is
// assembled by the engine from the rule pack — no model wrote a sentence of it.
export function DraftPane({ data, busy, onEvidence, onFiled, onDecision }: Props) {
  const [copied, setCopied] = useState(false);
  const [filedOn, setFiledOn] = useState("");
  const [decidedOn, setDecidedOn] = useState("");
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
  const evidenceLabel = new Map(
    [...readiness.present, ...missingDocs].map((item) => [item.id, item.label] as const),
  );
  const externalNext = data.state === "EXTERNAL_REVIEW_ELIGIBLE";

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
                  title={
                    c.provenance?.quote
                      ? `“${c.provenance.quote}” — page ${c.provenance.page}`
                      : "Stated by a person"
                  }
                >
                  {fieldLabel(c.field)}
                </span>
              ))}
              {p.evidence.map((ev) => (
                <span key={ev} className="cite evidence">
                  encl. {evidenceLabel.get(ev) ?? ev}
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
              <p>
                <strong>Not written.</strong>{" "}
                {o.missing_facts.length > 0 && (
                  <>The letter does not establish: {o.missing_facts.map(fieldLabel).join(", ")}. </>
                )}
                {o.missing_evidence.length > 0 && (
                  <>
                    Not on file:{" "}
                    {o.missing_evidence.map((id) => evidenceLabel.get(id) ?? id).join("; ")}.
                  </>
                )}
              </p>
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
                <span className="tag ok">on file</span>
                <span>{i.label}</span>
              </li>
            ))}
            {missingDocs.map((i) => (
              <li key={i.id} className={i.blocking ? "missing blocking" : "missing"}>
                <span className="tag">{i.blocking ? "needed" : "optional"}</span>
                <span>
                  {i.label}
                  {i.human_only && <span className="muted small"> · only you can obtain this</span>}
                </span>
                <button className="quiet-btn" disabled={busy} onClick={() => onEvidence(i.id)}>
                  Mark on file
                </button>
              </li>
            ))}
          </ul>
        </section>

        {FINISHED.includes(data.state) ? (
          <section>
            <h3>Outcome</h3>
            <p>{STATE_LABEL[data.state] ?? data.state}. This file is finished.</p>
          </section>
        ) : AWAITING_DECISION.includes(data.state) ? (
          <section>
            <h3>Decision</h3>
            <p className="muted small">
              Record the decision when you receive it.
              {data.state !== "EXTERNAL_REVIEW" && " An upheld internal appeal opens external review."}
            </p>
            <div className="value-form">
              <input type="date" value={decidedOn} onChange={(e) => setDecidedOn(e.target.value)} />
              <button disabled={busy || !decidedOn} onClick={() => onDecision("overturned", decidedOn)}>
                Overturned
              </button>
              <button disabled={busy || !decidedOn} onClick={() => onDecision("upheld", decidedOn)}>
                Upheld
              </button>
            </div>
          </section>
        ) : (
          <section>
            <h3>{externalNext ? "External review" : "Filing"}</h3>
            <form
              className="value-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (filedOn) onFiled(filedOn);
              }}
            >
              <input type="date" value={filedOn} onChange={(e) => setFiledOn(e.target.value)} />
              <button type="submit" disabled={busy || !filedOn}>
                {externalNext ? "Record external review request" : "Record as filed"}
              </button>
              <span className="muted small">
                {externalNext
                  ? "A record that you requested external review. Starts the reviewer's clock."
                  : "A record that you sent it. Starts the plan's response clock."}
              </span>
            </form>
          </section>
        )}
      </aside>
    </div>
  );
}
