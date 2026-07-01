import { statusClass } from "../lib.js";

/**
 * Compact labeled status tile (e.g. one memory layer, one tier mini-tile).
 * props: label, status, value?, sub?, onClick?
 */
export default function Cell({ label, status = "unknown", value, sub, onClick }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag className={`ic-cell ${statusClass(status)}`} onClick={onClick}>
      <div className="ic-cell-top">
        <span className="ic-cell-label">{label}</span>
        <span className="ic-cell-dot" />
      </div>
      {value != null && <div className="ic-cell-value t-mono">{value}</div>}
      {sub && <div className="ic-cell-sub t-caption">{sub}</div>}
    </Tag>
  );
}
