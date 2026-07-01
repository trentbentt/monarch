import { Card } from "../../design/primitives";
import { fmtAge, ageSeconds, statusClass } from "../../design/lib.js";
import "./MemoryMapCard.css";

const ORDER = ["L1", "L2", "L3", "L4", "L5", "L6", "L7"];

function layerStatus(l) {
  if (l?.anomaly) return "warn";
  const h = (l?.health || l?.health_signal || "").toLowerCase();
  if (h.includes("unhealth") || h.includes("down") || h.includes("dead")) return "crit";
  if (h.includes("degrad") || h.includes("idle") || h.includes("stale")) return "warn";
  if (h.includes("ok") || h.includes("health")) return "ok";
  return "unknown";
}

function fmtMs(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${Math.round(n)}ms`;
}

/** Memory map: the seven-layer architecture L1->L7 as a vertical ladder of
 *  rungs, plus the curated-GC and skill-draft queues and the last sweep. */
export default function MemoryMapCard({ state, status }) {
  const mem = state?.memory || {};
  const layers = mem.layers || {};
  const present = ORDER.filter((k) => layers[k]);

  if (present.length === 0) {
    return (
      <Card eyebrow="Memory" title="Memory architecture" status={status}>
        <div className="memory-empty t-caption">Memory layers not reporting.</div>
      </Card>
    );
  }

  const gcTotal = mem.gc_proposals_total ?? 0;
  const sdTotal = mem.skill_drafts_total ?? 0;
  const gcStale = (mem.gc_proposals_stale || []).length;
  const sdStale = (mem.skill_drafts_stale || []).length;
  const sweepAge = ageSeconds(mem.last_sweep);

  return (
    <Card eyebrow="Memory" title="Memory architecture" status={status}>
      <ol className="memory-ladder">
        {present.map((k) => {
          const l = layers[k];
          const st = layerStatus(l);
          const name = l.name || k;
          const role = l.anomaly || l.role || "";
          return (
            <li key={k} className={`memory-rung ${statusClass(st)}`}>
              <span className="memory-rung-id t-mono">{k}</span>
              <span className="memory-rung-dot" aria-hidden="true" />
              <span className="memory-rung-name">{name}</span>
              <span className={`memory-rung-role t-caption ${l.anomaly ? "is-anomaly" : ""}`}>
                {role}
              </span>
              <span className="memory-rung-ms t-mono">{fmtMs(l.response_ms)}</span>
            </li>
          );
        })}
      </ol>

      <div className="memory-queues">
        <Stat label="GC proposals" total={gcTotal} stale={gcStale} />
        <Stat label="Skill drafts" total={sdTotal} stale={sdStale} />
      </div>

      <div className="memory-foot t-caption">
        <span className="memory-foot-label">Last sweep</span>
        <span className="memory-foot-val t-mono">
          {sweepAge != null ? `${fmtAge(sweepAge)} ago` : (mem.last_sweep || "—")}
        </span>
      </div>
    </Card>
  );
}

function Stat({ label, total, stale }) {
  return (
    <div className={`memory-stat ${stale > 0 ? "st-warn" : ""}`}>
      <span className="eyebrow">{label}</span>
      <span className="memory-stat-row">
        <span className="t-metric-sm">{total}</span>
        {stale > 0 && <span className="memory-stale t-mono">{stale} stale</span>}
      </span>
    </div>
  );
}
