/**
 * The signature element: a cortical reactor core that ties the dashboard back to
 * the entrance's brain. Its color IS the overall system status; concentric rings
 * breathe, a neural shimmer drifts inside. One bold, living instrument — the rest
 * of the console stays quiet around it.
 *
 * Pure SVG + CSS so the global prefers-reduced-motion rule neutralizes its motion
 * automatically (no JS animation to special-case).
 */
const LABEL = {
  ok: "All systems nominal",
  warn: "Attention needed",
  crit: "Critical condition",
  unknown: "State unknown",
};

export default function ReactorOrb({ status = "unknown", size = 132 }) {
  const cls = `st-${status}`;
  return (
    <div className={`reactor ${cls}`} role="img" aria-label={LABEL[status] || LABEL.unknown}>
      <svg className="reactor-svg" viewBox="0 0 100 100" width={size} height={size} aria-hidden="true">
        <defs>
          <radialGradient id="reactor-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--st)" stopOpacity="0.95" />
            <stop offset="45%" stopColor="var(--st)" stopOpacity="0.30" />
            <stop offset="100%" stopColor="var(--st)" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* outer breathing rings */}
        <circle className="reactor-ring reactor-ring-3" cx="50" cy="50" r="44" />
        <circle className="reactor-ring reactor-ring-2" cx="50" cy="50" r="34" />
        <circle className="reactor-ring reactor-ring-1" cx="50" cy="50" r="24" />

        {/* radial nodes — a sparse neural lattice */}
        <g className="reactor-lattice">
          {Array.from({ length: 8 }).map((_, i) => {
            const a = (i / 8) * Math.PI * 2;
            return (
              <line
                key={i}
                x1={50 + Math.cos(a) * 12}
                y1={50 + Math.sin(a) * 12}
                x2={50 + Math.cos(a) * 40}
                y2={50 + Math.sin(a) * 40}
              />
            );
          })}
        </g>

        {/* radar pings — concentric pulses sweeping outward from the core */}
        <circle className="reactor-ping reactor-ping-1" cx="50" cy="50" r="9" />
        <circle className="reactor-ping reactor-ping-2" cx="50" cy="50" r="9" />
        <circle className="reactor-ping reactor-ping-3" cx="50" cy="50" r="9" />

        {/* glowing core */}
        <circle className="reactor-glow" cx="50" cy="50" r="40" fill="url(#reactor-core)" />
        <circle className="reactor-core" cx="50" cy="50" r="9" />
      </svg>
    </div>
  );
}
