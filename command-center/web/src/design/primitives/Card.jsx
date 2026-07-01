import StatusDot from "./StatusDot.jsx";
import { statusClass } from "../lib.js";

/**
 * Module shell — the instrument-panel frame every card uses.
 * props: eyebrow, title, status ('ok'|'warn'|'crit'|'unknown'),
 *        accent (force brass rail — reserve for the signature card),
 *        actions (right-aligned node), children.
 */
export default function Card({ eyebrow, title, status = "unknown", accent = false, actions, children, className = "" }) {
  return (
    <section className={`ic-card ${statusClass(status)} ${accent ? "ic-accent" : ""} ${className}`}>
      <span className="ic-rail" aria-hidden="true" />
      <header className="ic-head">
        <div className="ic-head-l">
          {eyebrow && <div className="eyebrow">{eyebrow}</div>}
          {title && <div className="t-title">{title}</div>}
        </div>
        <div className="ic-head-r">
          {actions}
          <StatusDot status={status} pulse />
        </div>
      </header>
      <div className="ic-body">{children}</div>
    </section>
  );
}
