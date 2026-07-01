import { statusClass } from "../lib.js";

/**
 * Compact vertical timeline of events. props: items [{t, label, status, sub?}],
 * windowLabel?. Renders a hairline spine with status nodes.
 */
export default function MiniTimeline({ items = [], windowLabel, empty = "Nothing recent." }) {
  if (!items.length) return <div className="ic-tl-empty t-caption">{empty}</div>;
  return (
    <div className="ic-tl">
      {windowLabel && <div className="eyebrow ic-tl-window">{windowLabel}</div>}
      <ul className="ic-tl-list">
        {items.map((it, i) => (
          <li key={i} className={`ic-tl-item ${statusClass(it.status)}`}>
            <span className="ic-tl-node" />
            <span className="ic-tl-t t-mono">{it.t}</span>
            <span className="ic-tl-label">{it.label}</span>
            {it.sub && <span className="ic-tl-sub t-caption">{it.sub}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
