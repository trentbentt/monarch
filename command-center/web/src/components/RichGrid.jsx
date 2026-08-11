import DomainCard from "./DomainCard.jsx";
import VitalsCard from "./cards/VitalsCard.jsx";
import EngineRoomCard from "./cards/EngineRoomCard.jsx";
import SpendCard from "./cards/SpendCard.jsx";
import MemoryMapCard from "./cards/MemoryMapCard.jsx";
import EventsCard from "./cards/EventsCard.jsx";
import ScheduleCard from "./cards/ScheduleCard.jsx";
import WorkflowsCard from "./cards/WorkflowsCard.jsx";
import RoutingCard from "./cards/RoutingCard.jsx";
import AuthorityCard from "./cards/AuthorityCard.jsx";
import MissionsCard from "./cards/MissionsCard.jsx";
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
  authority: AuthorityCard,
  missions: MissionsCard,
};

// Bento order: the two signature instruments lead (Vitals hero + Engine Room),
// then orchestration and the supporting domains. Each card carries id=card-<key>
// so the rail's domain index can jump to it. `docs` is intentionally absent — the
// functional Docs Router lives in the ops strip (DocsSearch); a status card would
// be a redundant second "docs router".
// Order is load-bearing for the layout, not just for reading order: the spans
// in shell.css (§10 step 3) tile the 4-column grid exactly in THIS sequence —
// vitals(2) tiers(2) | missions(4) | schedule(3) authority(1) |
// memory(2) events(2) | spend(2) routing(1) workflows(1). Reordering without
// re-checking the spans regrows the holes the weighting was written to remove.
//
// It also reads correctly: the two signature instruments lead, the substantive
// domains follow, and the two cards §5 measured as thin sit last — their
// narrowness states the upstream producer gap rather than hiding it behind
// equal width.
export const ORDER = [
  "vitals", "tiers", "missions", "schedule", "authority",
  "memory", "events", "spend", "routing", "workflows",
];

// Cards whose data does NOT come from `state.json` via the overview.
//
// Every other card is gated on `byKey[key]` — a domain the overview derived.
// The register is not a state.json domain: it is read by shelling the
// allocator, and adding a deriver for it would put a subprocess inside
// `derive_overview`, which recomputes on every state update and feeds the SSE
// stream. Gating the card on a domain that cannot honestly exist would mean
// either inventing one or never rendering the card.
//
// So these render unconditionally and fetch their own data, degrading on their
// own terms. Listed rather than special-cased inline so the exception is
// countable — one name here is a design decision, five would be a smell.
export const SELF_SOURCED = new Set(["missions"]);
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
    ...ORDER.filter((k) => byKey[k] || SELF_SOURCED.has(k)),
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
              aria-label={`Open ${d?.label || key} deep-dive`}
              title="Open deep-dive"
            >
              ⤢
            </button>
            {/* A self-sourced card has no overview domain, so it gets no
                derived status — it reports its own, including UNMEASURED.
                DomainCard is only the fallback for a domain that exists but
                has no rich card; a key with neither renders nothing rather
                than dereferencing an absent domain. */}
            {C
              ? <C state={state} status={d?.status} />
              : (d ? <DomainCard domain={d} /> : null)}
          </div>
        );
      })}
    </div>
  );
}
