import { statusClass, clamp } from "../lib.js";

/**
 * Horizontal bar with an optional threshold tick.
 * props: value, max, status, thresholdPct?, label, right? (right-aligned readout)
 */
export default function Meter({ value = 0, max = 100, status = "unknown", thresholdPct, label, right }) {
  const frac = clamp(max ? value / max : 0, 0, 1);
  return (
    <div className={`ic-meter ${statusClass(status)}`}>
      {(label || right) && (
        <div className="ic-meter-head">
          {label && <span className="t-caption">{label}</span>}
          {right && <span className="t-caption t-mono">{right}</span>}
        </div>
      )}
      <div className="ic-meter-track">
        <div className="ic-meter-fill" style={{ width: `${frac * 100}%` }} />
        {thresholdPct != null && <span className="ic-meter-thresh" style={{ left: `${thresholdPct}%` }} />}
      </div>
    </div>
  );
}
