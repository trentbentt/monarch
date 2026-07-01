import { statusClass } from "../lib.js";

/** Small status indicator. Pulses only on crit (deliberate, not decorative). */
export default function StatusDot({ status, pulse }) {
  const isCrit = status === "crit";
  return <span className={`ic-dot ${statusClass(status)} ${pulse && isCrit ? "ic-dot-pulse" : ""}`} aria-label={status} />;
}
