// Shared formatting + status helpers for card clusters.

export function statusClass(s) {
  return `st-${s || "unknown"}`;
}

/** seconds -> compact age, e.g. 45s, 12m, 3h, 4d */
export function fmtAge(s) {
  if (s == null) return "—";
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

/** MB -> GB with one decimal when large, else MB. */
export function fmtBytesMB(mb) {
  if (mb == null) return "—";
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

export function pct(a, b) {
  if (!b) return 0;
  return Math.round((100 * a) / b);
}

/** ISO timestamp -> seconds ago (or null). */
export function ageSeconds(iso) {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / 1000;
}

/** clamp a number into [lo, hi]. */
export function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n));
}
