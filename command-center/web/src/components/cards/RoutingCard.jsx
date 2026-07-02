import { Card } from "../../design/primitives";
import "./RoutingCard.css";

/** Request Routing: the path every model request takes to a tier —
 *  Router → Gate → Dispatcher → the inference tiers. Each hop shows its health;
 *  the destination shows which tiers are actually taking traffic. Derived from
 *  the same signals as the backend's derive_routing (health components + tiers). */

const STAGE = [
  { name: "litellm", label: "Router", sub: "picks model + tier, applies budget" },
  { name: "validation-gate", label: "Gate", sub: "gates news briefs; fail → retry, hold" },
  { name: "lora-dispatcher", label: "Dispatcher", sub: "loads the tier's LoRA" },
];

function interp(s) {
  const v = (s || "").toLowerCase();
  if (["ok", "healthy", "up", "online"].includes(v)) return "ok";
  if (["warn", "degraded"].includes(v)) return "warn";
  if (["crit", "down", "dead", "error", "unresponsive"].includes(v)) return "crit";
  return "unknown";
}

function comp(state, name) {
  return (state?.health?.components || []).find((c) => c.name === name) || null;
}

function Hop({ meta, c }) {
  const st = c ? interp(c.status) : "unknown";
  return (
    <div className={`route-hop lvl-${st}`}>
      <div className="route-hop-head">
        <span className="card-dot" />
        <span className="route-hop-label">{meta.label}</span>
      </div>
      <span className="route-hop-sub">{meta.sub}</span>
      <span className="route-hop-meta t-mono">
        {meta.name}{c?.port ? ` :${c.port}` : ""}{c?.response_ms != null ? ` · ${c.response_ms}ms` : ""}
      </span>
    </div>
  );
}

export default function RoutingCard({ state, status }) {
  const tiers = state?.tiers || {};
  const traffic = [];
  const loras = [];
  for (const [tid, t] of Object.entries(tiers)) {
    const perf = t?.performance || {};
    const lora = t?.config?.active_lora;
    if (lora) loras.push({ tier: tid, lora });
    const completions = perf.completions_in_window || 0;
    const errors = perf.errors_in_window || 0;
    if (completions || errors) traffic.push({ tier: tid, completions, errors });
  }

  return (
    <Card eyebrow="Request Routing" title="Request → tier path" status={status}>
      <p className="route-lede t-caption">
        How every model request reaches a tier — and whether each hop is healthy.
      </p>

      <div className="route-flow">
        {STAGE.map((meta, i) => (
          <div className="route-flow-item" key={meta.name}>
            <Hop meta={meta} c={comp(state, meta.name)} />
            <span className="route-arrow" aria-hidden="true">→</span>
          </div>
        ))}
        <div className="route-flow-item">
          <div className="route-hop route-hop-dest">
            <div className="route-hop-head">
              <span className="route-hop-label">Tiers</span>
            </div>
            <span className="route-hop-sub">
              {traffic.length === 0
                ? "no recent traffic"
                : traffic.map((t) => `${t.tier.toUpperCase()} (${t.completions}${t.errors ? `·${t.errors} err` : ""})`).join("  ")}
            </span>
          </div>
        </div>
      </div>

      {loras.length > 0 && (
        <div className="route-loras">
          <span className="route-loras-k eyebrow">Active LoRA</span>
          <span className="t-mono">{loras.map((l) => `${l.tier.toUpperCase()}: ${l.lora}`).join(" · ")}</span>
        </div>
      )}
    </Card>
  );
}
