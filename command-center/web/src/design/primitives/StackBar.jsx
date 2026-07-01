/**
 * Stacked horizontal segments (e.g. VRAM used-by-tier).
 * props: segments [{label, value, color?}], total, legend? (bool)
 * color defaults walk a restrained brass->steel ramp so it stays on-palette.
 */
const RAMP = ["#D8B45A", "#9FB0C3", "#6E8099", "#57B894", "#7C8AA0", "#4E5A6E", "#3A4456"];

export default function StackBar({ segments = [], total, legend = true }) {
  const sum = total || segments.reduce((a, s) => a + (s.value || 0), 0) || 1;
  const segs = segments.filter((s) => (s.value || 0) > 0);
  return (
    <div className="ic-stack">
      <div className="ic-stack-track">
        {segs.map((s, i) => (
          <div
            key={s.label}
            className="ic-stack-seg"
            style={{ width: `${((s.value || 0) / sum) * 100}%`, background: s.color || RAMP[i % RAMP.length] }}
            title={`${s.label}: ${s.value}`}
          />
        ))}
      </div>
      {legend && (
        <div className="ic-stack-legend">
          {segs.map((s, i) => (
            <span key={s.label} className="ic-stack-key">
              <span className="ic-stack-swatch" style={{ background: s.color || RAMP[i % RAMP.length] }} />
              <span className="t-caption">{s.label}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
