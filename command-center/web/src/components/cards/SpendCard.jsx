import { Card, Meter, Metric } from "../../design/primitives";
import { pct } from "../../design/lib.js";
import "./SpendCard.css";

function rowStatus(row) {
  const s = (row.status || "").toLowerCase();
  if (s === "over" || s === "critical" || s === "exhausted") return "crit";
  if (s === "warning" || s === "warn") return "warn";
  const up = row.used_pct, wt = row.threshold_warning_pct, ct = row.threshold_critical_pct;
  if (up != null && ct != null && up >= ct) return "crit";
  if (up != null && wt != null && up >= wt) return "warn";
  return "ok";
}

const usd = (n) => `$${n.toFixed(2)}`;

// The cloud peers are surfaced by their real API model, not their slot id.
const PROVIDER_LABEL = {
  peer_a: "DeepSeek V4 Flash",
  peer_b: "Kimi K2.6",
};
// Unconfigured placeholder slots we don't surface (no provider/budget recorded).
const HIDDEN_QUOTA = /^pro_\d+$/;

/** Spend: per-provider budget meters + today's total. Honest about unmetered
 *  subscription plans; no fabricated history. */
export default function SpendCard({ state, status }) {
  const quotas = state?.quotas?.quotas || {};
  const rows = Object.entries(quotas)
    .filter(([id]) => !HIDDEN_QUOTA.test(id))
    .map(([id, r]) => ({ id, ...r, name: PROVIDER_LABEL[id] || r?.name || id }));

  if (rows.length === 0) {
    return (
      <Card eyebrow="Spend" title="Cloud budget" status={status}>
        <div className="spend-empty t-caption">No providers tracked.</div>
      </Card>
    );
  }

  // budgeted (metered) rows first, then unmetered subscriptions
  const meteredOf = (r) => typeof r.budget_usd === "number" && r.budget_usd > 0;
  rows.sort((a, b) => meteredOf(b) - meteredOf(a));

  // Honest total: only sum rows that actually report a numeric spend.
  const spentRows = rows.filter((r) => typeof r.used_usd === "number");
  const haveSpend = spentRows.length > 0;
  const totalSpend = spentRows.reduce((a, r) => a + r.used_usd, 0);
  const meteredCount = rows.filter(meteredOf).length;

  // Aggregate health for the headline number.
  const worst = rows.reduce((acc, r) => {
    const st = rowStatus(r);
    if (st === "crit") return "crit";
    if (st === "warn" && acc !== "crit") return "warn";
    return acc;
  }, "ok");

  return (
    <Card eyebrow="Spend" title="Cloud budget" status={status}>
      <div className="spend-summary">
        <Metric
          value={haveSpend ? usd(totalSpend) : "—"}
          label="spent today"
          status={haveSpend ? worst : undefined}
        />
        <span className="spend-summary-sub t-caption">
          {meteredCount} of {rows.length} metered
        </span>
      </div>

      <div className="spend-rows">
        {rows.map((r) => {
          const metered = meteredOf(r);
          const st = rowStatus(r);
          const used = typeof r.used_usd === "number" ? r.used_usd : null;
          const p = metered && used != null ? pct(used, r.budget_usd) : null;
          return (
            <div className={`spend-row st-${st}`} key={r.id}>
              <div className="spend-row-head">
                <span className="spend-name">{r.name || r.id}</span>
                <span className="spend-fig t-mono">
                  {used != null ? usd(used) : "—"}
                </span>
              </div>

              {metered ? (
                <Meter
                  value={used || 0}
                  max={r.budget_usd}
                  status={st}
                  thresholdPct={r.threshold_warning_pct}
                  right={`${p != null ? `${p}%` : "—"} of ${usd(r.budget_usd)}`}
                />
              ) : (
                <div className="spend-sub">
                  <span className="spend-tag t-mono">no cap</span>
                  <span className="spend-sub-text t-caption">subscription</span>
                </div>
              )}

              {typeof r.burn_rate_per_hour === "number" && (
                <div className="spend-burn t-caption">
                  <span className="spend-burn-val t-mono">{usd(r.burn_rate_per_hour)}/h</span> burn
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
