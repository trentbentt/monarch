import { Card, MiniTimeline } from "../../design/primitives";
import { fmtAge, ageSeconds } from "../../design/lib.js";
import "./EventsCard.css";

function sevStatus(sev) {
  const s = (sev || "").toLowerCase();
  if (s === "critical" || s === "crit" || s === "error") return "crit";
  if (s === "warning" || s === "warn") return "warn";
  if (s === "info" || s === "debug") return "ok";
  return "unknown";
}

// Acronyms the operator reads as-is; everything else is sentence-cased.
const KEEP_CAPS = /^(gpu|cpu|vram|ram|oom|api|id|ttl|io|llm|kv)$/i;

function humanize(type) {
  const words = (type || "event").replace(/_/g, " ").trim().split(/\s+/);
  return words
    .map((w, i) => {
      if (KEEP_CAPS.test(w)) return w.toUpperCase();
      if (i === 0) return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
      return w.toLowerCase();
    })
    .join(" ");
}

/** Events: a calm operations log with a severity tally and retention window. */
export default function EventsCard({ state, status }) {
  const log = Array.isArray(state?.events?.log) ? state.events.log : [];
  const retention = state?.events?.retention_hours;

  // Newest first — events are appended chronologically; cap the visible window.
  const recent = log.slice(-12).reverse();

  const counts = { ok: 0, warn: 0, crit: 0 };
  for (const e of log) {
    const st = sevStatus(e?.severity);
    if (st === "crit") counts.crit++;
    else if (st === "warn") counts.warn++;
    else counts.ok++; // info/debug/unknown — informational by default
  }

  const items = recent.map((e) => {
    const label = humanize(e?.type);
    const raw = typeof e?.detail === "string" ? e.detail.trim() : "";
    // Suppress detail when it merely restates the humanized type.
    const sub = raw && raw.toLowerCase() !== label.toLowerCase() ? raw : null;
    return {
      t: fmtAge(ageSeconds(e?.timestamp)),
      label,
      status: sevStatus(e?.severity),
      sub,
    };
  });

  const windowLabel =
    retention != null ? `Last ${retention}h` : log.length ? "Retention window" : null;

  return (
    <Card eyebrow="Events" title="Event stream" status={status}>
      {log.length > 0 ? (
        <div className="events-tally">
          <span className="events-c info">
            <b className="t-mono">{counts.ok}</b> info
          </span>
          <span className="events-c warn">
            <b className="t-mono">{counts.warn}</b> warn
          </span>
          <span className="events-c crit">
            <b className="t-mono">{counts.crit}</b> crit
          </span>
        </div>
      ) : null}
      <MiniTimeline
        items={items}
        windowLabel={windowLabel}
        empty="No events in the retention window."
      />
    </Card>
  );
}
