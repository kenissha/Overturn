import { useEffect, useState } from "react";
import { api, type CaseSummary, type Queue as QueueData } from "../api";
import { NewFile } from "../components/NewFile";
import { daysText, fieldLabel, fmtDate, TRIGGER_LABEL } from "../format";

// Screen 1. Not a table of forty rows: the few files that need a person today, each with
// the reason, and one quiet line for everything the system is carrying on its own.
export function Queue({ extractor }: { extractor: boolean }) {
  const [data, setData] = useState<QueueData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .queue()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) return <p className="error">Could not load today's queue: {error}</p>;
  if (!data) return <p className="muted pad">Loading…</p>;

  const empty = data.attention.length === 0 && data.quiet_count === 0;

  return (
    <div className="queue">
      <div className="queue-head">
        <div>
          <h1>Today</h1>
          <p className="muted">{fmtDate(data.today)}</p>
        </div>
        <NewFile />
      </div>

      {empty ? (
        <div className="empty">
          <p>No files yet.</p>
          <p className="muted">
            Start one by uploading a denial letter. {extractor ? "" : "Reading is off, so the letter will be stored and scanned but not read."}
          </p>
        </div>
      ) : data.attention.length === 0 ? (
        <div className="empty">
          <p>Nothing needs you today.</p>
        </div>
      ) : (
        <div className="cards">
          {data.attention.map((c) => (
            <QueueCard key={c.case_id} summary={c} />
          ))}
        </div>
      )}

      {data.quiet_count > 0 && (
        <p className="quiet">
          <a href="#/files">
            {data.quiet_count} {data.quiet_count === 1 ? "file is" : "files are"} progressing in the
            background
          </a>
          {data.attention_total > data.attention.length && (
            <span className="muted">
              {" "}
              · {data.attention_total - data.attention.length} more waiting on you
            </span>
          )}
        </p>
      )}
    </div>
  );
}

function QueueCard({ summary }: { summary: CaseSummary }) {
  const top = summary.top;
  const due = summary.next_deadline;
  return (
    <a className={`card p-${summary.highest_pressure}`} href={`#/case/${summary.case_id}`}>
      <div className="card-meta">
        <span>{summary.service ?? "Unread letter"}</span>
        <span className="muted">{summary.issuer ?? ""}</span>
      </div>
      {top && (
        <>
          <span className={`chip t${top.trigger}`}>{TRIGGER_LABEL[top.trigger]}</span>
          <p className="card-question">{top.question}</p>
          <p className="card-why">{top.why_it_matters}</p>
        </>
      )}
      <div className="card-foot">
        {due ? (
          <span className={`due p-${due.pressure}`}>
            {fieldLabel(due.field)} {fmtDate(due.due)} · {daysText(due.days_remaining)}
            {due.basis === "regime_default" && <span className="muted"> · statutory default</span>}
          </span>
        ) : (
          <span className="muted">No deadline can be computed yet</span>
        )}
        {summary.escalation_count > 1 && (
          <span className="muted">{summary.escalation_count - 1} more</span>
        )}
      </div>
    </a>
  );
}
