import { Card, Cell, Sentence } from "../../design/primitives";
import { ageSeconds, fmtAge } from "../../design/lib.js";
import "./WorkflowsCard.css";
import CardTrend from "./CardTrend.jsx";

const STATUS_WORD = { ok: "Online", warn: "Degraded", crit: "Down", unknown: "Unknown" };

function comp(state, name) {
  const comps = state?.health?.components || [];
  return comps.find((c) => c.name === name) || null;
}

/**
 * What the orchestration reading MEANS.
 *
 * The card can only see whether n8n answers its port — state.json carries no
 * workflow inventory, no run counts and no outcomes, and the metrics substrate
 * serves no workflow series. So a healthy engine is stated as exactly that, and
 * the gap is named rather than left for the operator to infer from green.
 * (M152/M154: a lane measuring its OUTPUT has not measured its OUTCOME.)
 */
export function sentence(n8n, status) {
  if (!n8n) return "The n8n health feed is not reporting, so orchestration state is unknown.";
  if (status === "crit") return "n8n is down, so no workflow can be running.";
  if (status === "warn") return "n8n is degraded — workflows may be running slowly or failing to trigger.";
  if (status === "unknown") return "n8n's status is unreported, so orchestration state is unknown.";
  const ms = n8n.response_ms;
  const lat = ms == null ? "" : ` at ${ms}ms`;
  return `n8n is online${lat}. No workflow outcomes are reported to the console, so this reading covers the engine, not the work it runs.`;
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

        <Sentence text={sentence(n8n, status)} />
      </div>
      <CardTrend card="workflows" />
    </Card>
  );
}
