import { useEffect, useState } from "react";
import { api, type CaseSummary } from "../api";
import { NewFile } from "../components/NewFile";
import { daysText, fmtDate, STATE_LABEL } from "../format";

export function CaseList() {
  const [rows, setRows] = useState<CaseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .cases()
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) return <p className="error">Could not load files: {error}</p>;
  if (!rows) return <p className="muted pad">Loading…</p>;

  return (
    <div className="files">
      <div className="queue-head">
        <h1>All files</h1>
        <NewFile />
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Service</th>
              <th>Insurer</th>
              <th>Category</th>
              <th>State</th>
              <th>Next deadline</th>
              <th>Needs you</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.case_id} onClick={() => (window.location.hash = `/case/${r.case_id}`)}>
                <td>{r.service ?? <span className="muted">Unread letter</span>}</td>
                <td>{r.issuer ?? "—"}</td>
                <td>{r.pack ?? "—"}</td>
                <td>{STATE_LABEL[r.state] ?? r.state}</td>
                <td className={r.next_deadline ? `p-${r.next_deadline.pressure} due` : ""}>
                  {r.next_deadline
                    ? `${fmtDate(r.next_deadline.due)} · ${daysText(r.next_deadline.days_remaining)}`
                    : "—"}
                </td>
                <td>{r.escalation_count || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
