import ReactorOrb from "./ReactorOrb.jsx";
import { navigate } from "../../hooks/useHashRoute.js";

/**
 * The console spine. Top: the reactor orb (overall status, the signature).
 * Middle: the 10 domains as a navigable index — each a status-dotted jump link
 * to its card. Bottom: the live connection read-out. Collapses to a top strip
 * on phones (CSS).
 *
 * Domain order mirrors the bento: signature instruments first.
 */
const NAV = [
  { key: "vitals", label: "Vitals" },
  { key: "tiers", label: "Engine Room" },
  { key: "workflows", label: "Workflows" },
  { key: "spend", label: "Spend" },
  { key: "memory", label: "Memory Map" },
  { key: "events", label: "Events" },
  { key: "schedule", label: "Schedule" },
  { key: "routing", label: "Request Routing" },
  { key: "authority", label: "Authority" },
];

const CONN_LABEL = { live: "live", polling: "polling", offline: "offline" };

function jump(key) {
  const el = document.getElementById(`card-${key}`);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
}

export default function SideRail({ overview, conn }) {
  const overall = overview?.overall || "unknown";
  const byKey = Object.fromEntries((overview?.domains || []).map((d) => [d.key, d]));
  const crit = (overview?.attention || []).filter((a) => a.status === "crit").length;
  const warn = (overview?.attention || []).filter((a) => a.status === "warn").length;

  return (
    <aside className="rail">
      <div className="rail-brand">
        <ReactorOrb status={overall} />
        <div className="rail-brand-meta">
          <h1 className="rail-title">Monarch</h1>
          <div className={`rail-overall t-mono st-${overall}`}>
            {overall === "ok" && "nominal"}
            {overall === "warn" && `${warn} warning${warn === 1 ? "" : "s"}`}
            {overall === "crit" && `${crit} critical`}
            {overall === "unknown" && "awaiting state"}
          </div>
        </div>
      </div>

      <nav className="rail-nav" aria-label="Domains">
        <div className="eyebrow rail-nav-head">Domains</div>
        <ul>
          {NAV.map((n) => {
            const d = byKey[n.key];
            const st = d?.status || "unknown";
            return (
              <li key={n.key}>
                <button className={`rail-link st-${st}`} onClick={() => jump(n.key)}>
                  <span className="rail-link-dot" aria-hidden="true" />
                  <span className="rail-link-label">{n.label}</span>
                  {d?.summary && <span className="rail-link-sum t-mono">{d.summary}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <nav className="rail-explore" aria-label="Explore">
        <div className="eyebrow rail-nav-head">Explore</div>
        <ul>
          <li>
            <button className="rail-link" onClick={() => navigate("/deep/codebase")}>
              <span className="rail-link-dot rail-link-dot-cyan" aria-hidden="true" />
              <span className="rail-link-label">Codebase Map</span>
              <span className="rail-link-sum t-mono">L5 index</span>
            </button>
          </li>
        </ul>
      </nav>

      <div className="rail-foot">
        <span className={`rail-conn conn-${conn}`}>
          <span className="rail-conn-dot" aria-hidden="true" />
          {CONN_LABEL[conn] || conn}
        </span>
        {overview?.daemon_pid != null && (
          <span className="rail-pid t-mono">pid {overview.daemon_pid}</span>
        )}
      </div>
    </aside>
  );
}
