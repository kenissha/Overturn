import type { Case } from "../api";
import { daysText, fieldLabel, fmtDate, PRESSURE_LABEL } from "../format";

const DAY = 86_400_000;
const ms = (iso: string) => new Date(iso.slice(0, 10) + "T00:00:00").getTime();

// Screen 3. One line per clock: from the date that started it, past today, to the day it
// runs out. Colour changes with pressure and with nothing else. A date inferred from the
// statute is drawn dashed; a date printed in the letter is drawn solid.
export function DeadlineStrip({ deadlines, today }: { deadlines: Case["deadlines"]; today: string }) {
  const rows = deadlines.deadlines;

  if (!rows.length && !deadlines.blocked.length) return null;

  const start = Math.min(ms(today), ...rows.map((d) => ms(d.anchor_date)));
  const end = Math.max(ms(today) + 7 * DAY, ...rows.map((d) => ms(d.due)));
  const span = Math.max(end - start, DAY);
  const pos = (iso: string) => `${(((ms(iso) - start) / span) * 100).toFixed(2)}%`;

  return (
    <div className="strip">
      {rows.map((d) => (
        <div key={d.field} className={`strip-row p-${d.pressure} ${d.met_on ? "met" : ""}`}>
          <div className="strip-label">
            <strong>{fieldLabel(d.field)}</strong> {fmtDate(d.due)}{" "}
            {d.met_on ? (
              <span className="strip-met">met · filed {fmtDate(d.met_on)}</span>
            ) : (
              <span className="strip-days">{daysText(d.days_remaining)}</span>
            )}
            {PRESSURE_LABEL[d.pressure] && <span className="strip-pressure"> · {PRESSURE_LABEL[d.pressure]}</span>}
            <div className="muted small">
              {d.basis === "stated_in_letter" ? "Printed in the letter." : `Statutory default: ${d.rule}.`}
              {d.anchor_is_estimated &&
                " Receipt date unknown, so the notice date was used — this is the earliest possible deadline, not the exact one."}
            </div>
          </div>
          <div className="track">
            <div
              className={`bar ${d.basis === "regime_default" ? "dashed" : ""}`}
              style={{ left: pos(d.anchor_date), right: `calc(100% - ${pos(d.due)})` }}
            />
            <div className="tick anchor" style={{ left: pos(d.anchor_date) }} title={`${fieldLabel(d.anchor_field)} ${fmtDate(d.anchor_date)}`} />
            <div className="tick today" style={{ left: pos(today) }} title="Today" />
            <div className="tick due" style={{ left: pos(d.due) }} title={`Due ${fmtDate(d.due)}`} />
          </div>
        </div>
      ))}
      {deadlines.blocked.map((b) => (
        <div key={b.field} className="strip-blocked">
          <strong>{fieldLabel(b.field)}</strong>: cannot be computed yet.{" "}
          <span className="muted">{b.explanation}</span>
        </div>
      ))}
    </div>
  );
}
