/**
 * Pure notification-decision logic — a faithful mirror of the server's
 * `should_notify` / `build_payload` (server/push/bridge.py) and
 * `CC_PUSH_INTERRUPT_TYPES` (server/config.py). Kept free of Tauri imports so it
 * can be unit-tested directly. Keep in sync with the server.
 */

// Mirror of server/config.py PUSH_INTERRUPT_TYPES (default set).
export const INTERRUPT_TYPES = new Set([
  "gpu_thermal_critical",
  "security_alert",
  "spend_burst",
  "ram_exhaustion",
]);

export const CRITICAL_SEV = new Set(["critical", "crit", "error"]);

/** Parse "HH:MM" to minutes-since-midnight, or null if malformed. */
export function parseHHMM(s) {
  if (!s || typeof s !== "string") return null;
  const [h, m] = s.split(":");
  const hh = Number(h);
  const mm = Number(m);
  if (Number.isNaN(hh) || Number.isNaN(mm)) return null;
  return hh * 60 + mm;
}

/** Mirror of in_overnight_window(): handles windows that wrap past midnight. */
export function inOvernightWindow(prefs, now) {
  const start = parseHHMM(prefs?.overnight_window_start);
  const end = parseHHMM(prefs?.overnight_window_end);
  if (start == null || end == null) return false;
  const t = now.getHours() * 60 + now.getMinutes();
  return start <= end ? t >= start && t < end : t >= start || t < end;
}

/** Mirror of should_notify(): interrupt classes always fire; otherwise critical
 * severity fires unless we are inside the operator's overnight quiet window. */
export function shouldNotify(event, prefs, now) {
  const etype = event?.type || "";
  const sev = (event?.severity || "").toLowerCase();
  if (INTERRUPT_TYPES.has(etype)) return true; // bypasses quieting
  if (inOvernightWindow(prefs, now)) return false; // quieted
  return CRITICAL_SEV.has(sev);
}

/** Mirror of build_payload(): title/body for the OS notification. */
export function buildNotification(event) {
  const etype = event?.type || "event";
  const sev = event?.severity || "info";
  return {
    title: `Monarch · ${etype}`,
    body: event?.detail || `${sev} event on ${event?.tier || "system"}`,
  };
}
