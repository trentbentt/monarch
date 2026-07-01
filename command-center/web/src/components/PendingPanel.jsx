import { useTick } from "../hooks/useTick.js";

function remaining(expiresAt) {
  if (!expiresAt) return null;
  const ms = new Date(expiresAt).getTime() - Date.now();
  return Math.max(0, Math.round(ms / 1000));
}

function VetoCountdown({ expiresAt }) {
  const s = remaining(expiresAt);
  if (s == null) return null;
  const cls = s <= 15 ? "veto-crit" : s <= 45 ? "veto-warn" : "veto-ok";
  return (
    <span className={`veto ${cls}`}>
      {s > 0 ? `auto-proceeds in ${s}s` : "auto-proceeding…"}
    </span>
  );
}

/** Legibility panel: what Loki wants to do, WHY, its trust state, and (for
 *  non-blocking Tier-3) a live veto countdown. Phase 3: approve/veto if paired. */
export default function PendingPanel({ pending, openConfirm }) {
  useTick(1000); // keep countdowns live
  if (!pending || pending.length === 0) {
    return (
      <section className="panel">
        <h2>Pending decisions</h2>
        <div className="attention-empty">No actions awaiting you. Loki is idle or autonomous within trust.</div>
      </section>
    );
  }
  return (
    <section className="panel">
      <h2>Pending decisions</h2>
      <ul className="pending">
        {pending.map((p, i) => (
          <li key={p.action_id || i} className={`pending-item tier-${p.tier || ""}`}>
            <div className="pending-head">
              <span className="pending-title">{p.description || p.action_id}</span>
              {p.tier && <span className="chip">{String(p.tier).replace("ActionTier.", "")}</span>}
              {p.kind && <span className="chip chip-muted">{p.kind}</span>}
              {!p.blocking && <VetoCountdown expiresAt={p.expires_at} />}
            </div>
            {p.rationale && <div className="pending-why"><b>Why:</b> {p.rationale}</div>}
            <div className="pending-meta">
              {p.ledger_state && <span>trust: {p.ledger_state}</span>}
              {p.current_tier != null && p.target_tier != null && (
                <span>tier {p.current_tier}→{p.target_tier}</span>
              )}
              {p.clean_run_count != null && (
                <span>clean {p.clean_run_count}/{p.total_runs ?? "?"}</span>
              )}
              {p.last_outcome && <span>last: {p.last_outcome}</span>}
            </div>
            {openConfirm && p.action_id && (
              <div className="pending-controls">
                <button
                  className="docs-btn sm"
                  onClick={() => openConfirm({ action: "approve", params: { action_id: p.action_id },
                    label: `Approve: ${p.description || p.action_id}`, danger: "reversible" })}
                >
                  Approve
                </button>
                <button
                  className="docs-btn ghost sm"
                  onClick={() => openConfirm({ action: "veto", params: { action_id: p.action_id },
                    label: `Veto: ${p.description || p.action_id}`, danger: "reversible" })}
                >
                  Veto
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
