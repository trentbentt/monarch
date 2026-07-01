const LABELS = { ok: "All systems nominal", warn: "Needs attention", crit: "Critical", unknown: "Unknown" };

export default function StatusPill({ status, stale }) {
  const s = status || "unknown";
  return (
    <div className={`pill pill-${s}`}>
      <span className="pill-dot" />
      <span className="pill-label">{LABELS[s]}</span>
      {stale && <span className="pill-stale">stale data</span>}
    </div>
  );
}
