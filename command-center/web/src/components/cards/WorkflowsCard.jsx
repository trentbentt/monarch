import { Card, Cell } from "../../design/primitives";
import { ageSeconds, fmtAge } from "../../design/lib.js";
import "./WorkflowsCard.css";

const STATUS_WORD = { ok: "Online", warn: "Degraded", crit: "Down", unknown: "Unknown" };

function comp(state, name) {
  const comps = state?.health?.components || [];
  return comps.find((c) => c.name === name) || null;
}

/** Workflows = the n8n orchestration engine. Shows the engine's live health, the
 *  port it answers on, round-trip latency, and how long since it was last seen
 *  healthy — the operator's at-a-glance read on whether automation is flowing. */
export default function WorkflowsCard({ state, status }) {
  const n8n = comp(state, "n8n");
  const lastHealthy = ageSeconds(n8n?.last_seen_healthy);
  const ms = n8n?.response_ms;
  const word = STATUS_WORD[status] || STATUS_WORD.unknown;

  return (
    <Card eyebrow="Workflows" title="Orchestration" status={status}>
      <div className="wf">
        <div className={`wf-engine st-${status}`}>
          <span className="wf-engine-dot" aria-hidden="true" />
          <div className="wf-engine-meta">
            <div className="t-metric-sm wf-engine-state">{word}</div>
            <div className="t-caption">n8n automation engine</div>
          </div>
        </div>

        <div className="wf-cells">
          <Cell label="Port" status={status} value={n8n?.port ?? "—"} />
          <Cell
            label="Latency"
            status={ms == null ? "unknown" : ms < 250 ? "ok" : ms < 1000 ? "warn" : "crit"}
            value={ms == null ? "—" : `${ms} ms`}
          />
          <Cell
            label="Last healthy"
            status={lastHealthy == null ? "unknown" : lastHealthy < 120 ? "ok" : "warn"}
            value={fmtAge(lastHealthy)}
            sub="ago"
          />
        </div>

        {n8n?.detail && <div className="wf-detail t-caption">{n8n.detail}</div>}
      </div>
    </Card>
  );
}
