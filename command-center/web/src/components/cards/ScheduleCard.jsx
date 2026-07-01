import { Card, MiniTimeline, Cell } from "../../design/primitives";
import "./ScheduleCard.css";

/** ISO -> stable 24h HH:MM for the instrument readout, or em-dash. */
function clock(iso) {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "—";
  return t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** Schedule: cron reconciliation — what's next, what slipped. */
export default function ScheduleCard({ state, status }) {
  const sched = state?.schedule;
  const hasData = sched != null;
  const s = sched || {};

  const upcoming = (s.upcoming_60min || [])
    .filter((u) => u && !Number.isNaN(new Date(u.next_run).getTime()))
    .slice()
    .sort((a, b) => new Date(a.next_run) - new Date(b.next_run));
  const missed = (s.missed_runs_24h || []).length;
  const collisions = (s.collisions || []).length;
  const stale = (s.stale_entries || []).filter(Boolean);

  // Count tiles read "—" (unknown) when there's no schedule payload at all,
  // so an absent feed never masquerades as a clean board.
  const tile = (n) => (hasData ? n : "—");
  const tileStatus = (n) => (!hasData ? "unknown" : n > 0 ? "warn" : "ok");

  const items = upcoming.map((u) => ({
    t: clock(u.next_run),
    label: u.name || "unnamed job",
    status: "ok",
  }));

  const emptyMsg = hasData
    ? "Nothing scheduled in the next hour."
    : "No schedule data — feed offline.";

  return (
    <Card eyebrow="Schedule" title="Cron reconciliation" status={status}>
      <div className="schedule-stats">
        <Cell label="Missed" sub="last 24h" status={tileStatus(missed)} value={tile(missed)} />
        <Cell label="Collisions" sub="overlapping" status={tileStatus(collisions)} value={tile(collisions)} />
        <Cell label="Stale" sub="entries" status={tileStatus(stale.length)} value={tile(stale.length)} />
      </div>

      <div className="schedule-tl">
        <MiniTimeline items={items} windowLabel="Next 60 minutes" empty={emptyMsg} />
      </div>

      {stale.length > 0 && (
        <div className="schedule-stale">
          <span className="schedule-stale-dot st-warn" aria-hidden="true" />
          <span className="schedule-stale-body t-caption">
            <span className="schedule-stale-lead">Target script missing</span> for{" "}
            <span className="schedule-stale-names t-mono">{stale.join(", ")}</span>.
          </span>
        </div>
      )}
    </Card>
  );
}
