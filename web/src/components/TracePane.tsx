import { useEffect, useState } from "react";
import { api, type AuditEvent, type Case } from "../api";
import { fieldLabel, fmtTime, STATE_LABEL } from "../format";

// Screen 5. What happened to this file and who did it: every write the agent attempted,
// including the ones the ledger refused, and every move of the case state. Refusals are
// shown, not hidden — an agent trying to write something it may not is itself a finding.
export function TracePane({ data }: { data: Case }) {
  const [audit, setAudit] = useState<AuditEvent[] | null>(null);

  useEffect(() => {
    api.audit(data.case_id).then(setAudit).catch(() => setAudit([]));
  }, [data.case_id, data.updated_at]);

  const refused = audit?.filter((e) => e.outcome === "refused").length ?? 0;

  return (
    <div className="trace">
      <section>
        <h3>State</h3>
        <ol className="timeline">
          {data.history.map((t, i) => (
            <li key={i}>
              <span className="mono small">{fmtTime(t.at)}</span>{" "}
              <strong>{STATE_LABEL[t.to] ?? t.to}</strong> <span className="muted">by {t.by}</span>
              <div className="muted small">{t.reason}</div>
            </li>
          ))}
          {data.history.length === 0 && <li className="muted">No state changes yet.</li>}
        </ol>
      </section>

      <section>
        <h3>
          Ledger writes {audit && <span className="muted">· {audit.length} attempted, {refused} refused</span>}
        </h3>
        <div className="table-wrap">
          <table className="audit">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Field</th>
                <th>Outcome</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {audit?.map((e, i) => (
                <tr key={i} className={e.outcome}>
                  <td className="mono small">{fmtTime(e.at)}</td>
                  <td className="mono small">{e.actor}</td>
                  <td>{fieldLabel(e.field)}</td>
                  <td>{e.outcome === "refused" ? `refused · ${e.error_type}` : "accepted"}</td>
                  <td className="small">{e.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {data.answers.length > 0 && (
        <section>
          <h3>Answers given</h3>
          <ul className="plain">
            {data.answers.map((a) => (
              <li key={a.id}>
                <span className="mono small">{fmtTime(a.at)}</span> {a.by}: <strong>{a.answer}</strong>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
