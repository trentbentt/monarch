import { statusClass } from "../lib.js";

/**
 * Minimal SVG sparkline. props: points [n], status, width?, height?, fill?
 */
export default function Sparkline({ points = [], status = "unknown", width = 120, height = 32, fill = true }) {
  if (!points.length) return <svg width={width} height={height} className="ic-spark" />;
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const span = max - min || 1;
  const dx = points.length > 1 ? width / (points.length - 1) : width;
  const ys = points.map((p) => height - 2 - ((p - min) / span) * (height - 4));
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"} ${(i * dx).toFixed(1)} ${ys[i].toFixed(1)}`).join(" ");
  const area = `${line} L ${((points.length - 1) * dx).toFixed(1)} ${height} L 0 ${height} Z`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={`ic-spark ${statusClass(status)}`} preserveAspectRatio="none">
      {fill && <path d={area} className="ic-spark-area" />}
      <path d={line} className="ic-spark-line" fill="none" />
    </svg>
  );
}
