import { Card, Gauge, Meter, StackBar } from "../../design/primitives";
import { fmtBytesMB, pct } from "../../design/lib.js";
import "./VitalsCard.css";

const TIER_LABELS = { t1: "T1", t2: "T2", t3: "T3", t4: "T4", t5: "T5", t6: "T6", driver_display: "driver", other: "other" };

function vramStatus(oom) {
  const s = (oom || "").toLowerCase();
  if (s === "imminent") return "crit";
  if (s === "elevated") return "warn";
  if (!s) return "unknown";
  return "ok";
}

const OOM_NOTE = { imminent: "OOM imminent — shed a tier", elevated: "Headroom tightening" };

/** Signature card: VRAM radial dial vs the baseline target, used-by-tier split,
 *  and RAM / CPU vitals. The substrate's vital sign — the hero instrument. */
export default function VitalsCard({ state, status }) {
  const res = state?.resources || {};
  const vram = res.vram || {};
  const ram = res.ram || {};
  const cpu = res.cpu || {};
  const hw = state?.hardware || {};

  const hasVram = vram.total_mb != null && vram.total_mb > 0;
  const hasRam = ram.total_mb != null && ram.total_mb > 0;

  if (!hasVram && !hasRam) {
    return (
      <Card eyebrow="Vitals" title="Substrate vitals" status={status} accent>
        <div className="vitals-empty t-caption">Resources not reporting.</div>
      </Card>
    );
  }

  const segs = Object.entries(vram.used_by_tier || {})
    .map(([k, v]) => ({ label: TIER_LABELS[k] || k, value: v || 0 }))
    .filter((s) => s.value > 0);

  const ramPct = pct(ram.used_mb, ram.total_mb);
  const cores = hw.cpu?.cores_total;
  const load1 = cpu.load_avg_1m;
  const gpuName = (hw.gpu?.model || "").replace(/NVIDIA GeForce /i, "").trim();
  const ddr = hw.ram?.ddr_generation ? `${hw.ram.ddr_generation}${hw.ram.speed_mts ? `-${hw.ram.speed_mts}` : ""}` : null;

  const vStatus = vramStatus(vram.oom_risk);
  const oomNote = OOM_NOTE[(vram.oom_risk || "").toLowerCase()];
  const baseline = vram.baseline_target_pct;

  return (
    <Card eyebrow="Vitals" title="Substrate vitals" status={status} accent>
      <div className="vitals-grid">
        <div className="vitals-hero">
          {hasVram ? (
            <>
              <Gauge
                value={vram.used_mb || 0}
                max={vram.total_mb}
                baselinePct={baseline}
                label="VRAM"
                unit={`${fmtBytesMB(vram.used_mb)} / ${fmtBytesMB(vram.total_mb)}`}
                status={vStatus}
                size={196}
                accent
              />
              <div className={`vitals-hero-note t-caption t-mono st-${vStatus}`}>
                {oomNote ? (
                  <span className="vitals-oom">{oomNote}</span>
                ) : (
                  <span className="vitals-free">{fmtBytesMB(vram.free_mb)} free</span>
                )}
                {baseline != null && <span className="vitals-baseline">target {baseline}%</span>}
              </div>
            </>
          ) : (
            <div className="vitals-empty t-caption">VRAM not reporting.</div>
          )}
        </div>

        <div className="vitals-support">
          {segs.length > 0 && (
            <div className="vitals-block">
              <div className="eyebrow">VRAM by tier</div>
              <StackBar segments={segs} total={vram.total_mb} />
            </div>
          )}

          {hasRam && (
            <Meter
              label="System RAM"
              value={ram.used_mb || 0}
              max={ram.total_mb}
              status={ramPct >= 90 ? "crit" : ramPct >= 75 ? "warn" : "ok"}
              thresholdPct={90}
              right={`${fmtBytesMB(ram.used_mb)} / ${fmtBytesMB(ram.total_mb)}`}
            />
          )}

          {load1 != null && cores != null && cores > 0 && (
            <Meter
              label="CPU load · 1m"
              value={load1}
              max={cores}
              status={load1 >= cores ? "warn" : "ok"}
              thresholdPct={100}
              right={`${load1.toFixed(2)} / ${cores} cores`}
            />
          )}
        </div>
      </div>

      {(gpuName || ddr) && (
        <div className="vitals-foot t-caption t-mono">
          {gpuName && <span>{gpuName}</span>}
          {gpuName && ddr && <span className="vitals-foot-sep" aria-hidden="true">·</span>}
          {ddr && <span>{ddr}</span>}
        </div>
      )}
    </Card>
  );
}
