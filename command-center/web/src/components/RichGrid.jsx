import DomainCard from "./DomainCard.jsx";
import VitalsCard from "./cards/VitalsCard.jsx";
import EngineRoomCard from "./cards/EngineRoomCard.jsx";
import SpendCard from "./cards/SpendCard.jsx";
import MemoryMapCard from "./cards/MemoryMapCard.jsx";
import EventsCard from "./cards/EventsCard.jsx";
import ScheduleCard from "./cards/ScheduleCard.jsx";
import WorkflowsCard from "./cards/WorkflowsCard.jsx";
import RoutingCard from "./cards/RoutingCard.jsx";
import { navigate } from "../hooks/useHashRoute.js";

const RICH = {
  vitals: VitalsCard,
  tiers: EngineRoomCard,
  workflows: WorkflowsCard,
  spend: SpendCard,
  memory: MemoryMapCard,
  events: EventsCard,
  schedule: ScheduleCard,
  routing: RoutingCard,
};

// Bento order: the two signature instruments lead (Vitals hero + Engine Room),
// then orchestration and the supporting domains. Each card carries id=card-<key>
// so the rail's domain index can jump to it. `docs` is intentionally absent — the
// functional Docs Router lives in the ops strip (DocsSearch); a status card would
// be a redundant second "docs router".
const ORDER = [
  "vitals", "tiers", "workflows", "spend", "memory",
  "events", "schedule", "routing", "authority",
];
const HIDDEN = new Set(["docs"]);

// Cursor-tracking border: set --rotation to the angle from the card's centre to
// the pointer, so a cyan arc on the border follows the cursor (see .cursor-border
// in deepdive shell CSS). Pure CSS variable write — no React re-render.
function onCellMove(e) {
  const el = e.currentTarget;
  const r = el.getBoundingClientRect();
  const x = e.clientX - r.left - r.width / 2;
  const y = e.clientY - r.top - r.height / 2;
  el.style.setProperty("--rotation", `${Math.atan2(y, x)}rad`);
}

export default function RichGrid({ overview, state }) {
  const domains = (overview?.domains || []).filter((d) => !HIDDEN.has(d.key));
  const byKey = Object.fromEntries(domains.map((d) => [d.key, d]));

  // Open the full-page deep-dive for a domain (#/deep/<key>). Every card goes
  // deep — the workspace carries the scoped supervisor into the weeds.
  const openDeep = (key) => navigate(`/deep/${key}`);

  // Before the live `state` arrives we only have the rolled-up overview — render
  // the generic glass tiles so the bento is never empty.
  if (!state) {
    return (
      <div className="bento">
        {domains.map((d) => (
          <div className="bento-cell cursor-border" id={`card-${d.key}`} key={d.key} onMouseMove={onCellMove}>
            <DomainCard domain={d} />
          </div>
        ))}
      </div>
    );
  }

  const keys = [
    ...ORDER.filter((k) => byKey[k]),
    ...domains.map((d) => d.key).filter((k) => !ORDER.includes(k)),
  ];

  return (
    <div className="bento">
      {keys.map((key) => {
        const d = byKey[key];
        const C = RICH[key];
        return (
          <div
            className={`bento-cell bento-${key} cursor-border`}
            id={`card-${key}`}
            key={key}
            onMouseMove={onCellMove}
          >
            <button
              className="bento-expand"
              onClick={() => openDeep(key)}
              aria-label={`Open ${d.label} deep-dive`}
              title="Open deep-dive"
            >
              ⤢
            </button>
            {C ? <C state={state} status={d.status} /> : <DomainCard domain={d} />}
          </div>
        );
      })}
    </div>
  );
}
