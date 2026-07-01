import { Card, Meter } from "../../design/primitives";
import { fmtAge, fmtBytesMB, statusClass } from "../../design/lib.js";
import "./EngineRoomCard.css";

const ORDER = ["t1", "t2", "t3", "t4", "t5", "t6"];

function tierStatus(rt, cfg) {
  const s = (rt?.state || "").toLowerCase();
  if (s === "live" || s === "running") return "ok";
  if (s === "idle" || s === "soft_offload") return cfg?.burst_only ? "ok" : "warn";
  if (s === "unresponsive" || s === "down" || s === "error") return "crit";
  return "unknown";
}

/** Human-readable runtime state, underscores → spaces. */
function stateLabel(rt, disabled) {
  if (disabled) return "disabled";
  const s = rt?.state;
  if (!s) return "—";
  return String(s).replace(/_/g, " ");
}

function shortModel(m) {
  if (!m) return "—";
  return m.replace(/\.gguf$/i, "").split("/").pop();
}

function Tile({ id, tier, vramTotal }) {
  const cfg = tier?.config || {};
  const rt = tier?.runtime || {};
  const perf = tier?.performance || {};
  const r = tier?.resources || {};
  const disabled = cfg.enabled === false;
  const st = disabled ? "unknown" : tierStatus(rt, cfg);
  const tok = perf.tok_per_sec_recent;
  const base = perf.tok_per_sec_baseline;
  // throughput is degraded if recent sits well below its own baseline
  const degraded = tok != null && base != null && base > 0 && tok < base * 0.7;

  return (
    <div className={`engine-tile ${statusClass(st)} ${disabled ? "engine-off" : ""} ${id === "t1" ? "engine-tile-accent" : ""}`}>
      <div className="engine-tile-head">
        <span className="engine-id t-mono">{id.toUpperCase()}</span>
        <span className="engine-dot" />
        <span className="engine-state">{stateLabel(rt, disabled)}</span>
      </div>

      <div className="engine-model" title={cfg.model || undefined}>
        {shortModel(cfg.model)}
      </div>
      <div className="engine-sub t-caption t-mono">
        {cfg.quant || "—"}
        {cfg.context_size ? ` · ${(cfg.context_size / 1024).toFixed(0)}K ctx` : ""}
        {cfg.burst_only ? " · burst" : ""}
      </div>

      <div className="engine-meter">
        <Meter
          value={disabled ? 0 : r.vram_used_mb || 0}
          max={vramTotal || 24576}
          status={disabled ? "unknown" : st}
          right={disabled ? "—" : fmtBytesMB(r.vram_used_mb)}
        />
      </div>

      <div className="engine-readouts t-mono t-caption">
        <span className={degraded ? "engine-warn" : undefined}>
          {disabled ? "offline" : tok != null ? `${Math.round(tok)} tok/s` : "—"}
          {!disabled && base != null ? <span className="engine-base"> / {Math.round(base)}</span> : null}
        </span>
        <span>{!disabled && rt.uptime_sec != null ? fmtAge(rt.uptime_sec) : ""}</span>
      </div>

      <div className="engine-chips">
        {!disabled && rt.offloaded && (
          <span className="engine-chip warn">offload -ngl {rt.offload_ngl ?? "?"}</span>
        )}
        {!disabled && cfg.active_lora && (
          <span className="engine-chip">lora {cfg.active_lora}</span>
        )}
        {!disabled && rt.restart_count_24h > 0 && (
          <span className="engine-chip warn">{rt.restart_count_24h}× restart</span>
        )}
      </div>
    </div>
  );
}

/** Engine room: the six local inference tiers, each a compact instrument tile. */
export default function EngineRoomCard({ state, status }) {
  const tiers = state?.tiers || {};
  const vramTotal = state?.resources?.vram?.total_mb;
  const ids = ORDER.filter((id) => tiers[id]);

  return (
    <Card eyebrow="Engine room" title="Inference tiers" status={status} className="engine-card">
      {ids.length === 0 ? (
        <div className="engine-empty t-caption">Tiers not reporting.</div>
      ) : (
        <div className="engine-grid">
          {ids.map((id) => (
            <Tile key={id} id={id} tier={tiers[id]} vramTotal={vramTotal} />
          ))}
        </div>
      )}
    </Card>
  );
}
