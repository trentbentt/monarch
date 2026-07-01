import { statusClass, clamp } from "../lib.js";

/**
 * Signature radial dial. A brass arc sweeps a faint 270° track; an optional
 * redline tick marks a baseline (e.g. the 80% VRAM target). The value renders
 * as a large mono readout in the well.
 *
 * props: value, max, baselinePct? (0-100), label, unit, status, size?
 */
const SWEEP = 270;                 // degrees of visible track
const START = 135;                 // start angle (deg, SVG 0=east, clockwise)

function polar(cx, cy, r, deg) {
  const a = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

function arcPath(cx, cy, r, startDeg, sweepDeg) {
  const end = startDeg + sweepDeg;
  const [x1, y1] = polar(cx, cy, r, startDeg);
  const [x2, y2] = polar(cx, cy, r, end);
  const large = sweepDeg > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
}

export default function Gauge({ value = 0, max = 100, baselinePct, label, unit, status = "unknown", size = 168, accent = false }) {
  const frac = clamp(max ? value / max : 0, 0, 1);
  const cx = size / 2, cy = size / 2;
  const r = size / 2 - 14;
  const track = arcPath(cx, cy, r, START, SWEEP);
  const fill = arcPath(cx, cy, r, START, SWEEP * frac || 0.0001);
  const pctNum = max ? Math.round((value / max) * 100) : 0;

  let baselineTick = null;
  if (baselinePct != null) {
    const deg = START + (SWEEP * baselinePct) / 100;
    const [ix, iy] = polar(cx, cy, r - 9, deg);
    const [ox, oy] = polar(cx, cy, r + 9, deg);
    baselineTick = <line x1={ix} y1={iy} x2={ox} y2={oy} className="ic-gauge-baseline" />;
  }

  return (
    <div className={`ic-gauge ${statusClass(status)}${accent ? " ic-gauge-accent" : ""}`} style={{ width: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="ic-gauge-svg">
        <path d={track} className="ic-gauge-track" strokeWidth={10} fill="none" strokeLinecap="round" />
        <path d={fill} className="ic-gauge-fill" strokeWidth={10} fill="none" strokeLinecap="round" />
        {baselineTick}
      </svg>
      <div className="ic-gauge-well">
        <div className="t-metric-lg">{pctNum}<span className="ic-gauge-pct">%</span></div>
        {label && <div className="ic-gauge-label eyebrow">{label}</div>}
        {unit && <div className="t-caption t-mono">{unit}</div>}
      </div>
    </div>
  );
}
