/**
 * Full-page deep-dive workspace. A card opens this via the hash route
 * (#/deep/<key>); it takes the whole viewport and docks the scoped supervisor on
 * the right so the operator dives into the weeds *with* it.
 *
 * Layout: header (back · title · status · refresh) over a two-column body —
 * content (Overview | Raw signal tabs) and the docked SupervisorChat. The chat
 * is given scope={domain} so every turn is grounded in this section and can cite
 * its real source.
 */
import { useEffect, useMemo, useState, useCallback } from "react";
import { navigate } from "../../hooks/useHashRoute.js";
import { statusClass } from "../../design/lib.js";
import SupervisorChat from "../SupervisorChat.jsx";
import GenericDeepDive from "./GenericDeepDive.jsx";
import WorkflowsDeepDive from "./WorkflowsDeepDive.jsx";
import MemoryDeepDive from "./MemoryDeepDive.jsx";
import CodebaseDeepDive from "./CodebaseDeepDive.jsx";
import RawSignal, { sliceFor } from "./RawSignal.jsx";
import { apiFetch } from "../../control.js";
import VitalsCard from "../cards/VitalsCard.jsx";
import EngineRoomCard from "../cards/EngineRoomCard.jsx";
import RoutingCard from "../cards/RoutingCard.jsx";
import EventsCard from "../cards/EventsCard.jsx";
import ScheduleCard from "../cards/ScheduleCard.jsx";
import SpendCard from "../cards/SpendCard.jsx";
import "./deepdive.css";

// Bespoke Overview renderers by domain; everything else falls back to generic.
const BESPOKE = {
  workflows: WorkflowsDeepDive,
  memory: MemoryDeepDive,
  codebase: CodebaseDeepDive,
};

// Provider-less domains whose dashboard card *is* a serviceable Overview. These
// six render live from `state` (the same instruments shown on the bento), so the
// deep-dive reuses them as the Overview tab — no backend provider required.
// workflows/memory have richer bespoke deep-dives; authority/docs have no card.
export const CARD_OVERVIEW = {
  vitals: VitalsCard,
  tiers: EngineRoomCard,
  routing: RoutingCard,
  events: EventsCard,
  schedule: ScheduleCard,
  spend: SpendCard,
};

// What the content panel can show, given the fetch status, whether the live state
// carries a raw slice, and whether the domain has a card-based Overview. A
// provider-less ("notfound") domain is only a dead end when it has neither a card
// Overview nor a raw slice — vitals/tiers/routing/… have a card (and a slice), so
// they get a real Overview + Raw signal instead of a blank "nothing here".
export function panelMode(status, hasRawSlice, hasCardOverview = false) {
  if (status === "ready") return { overview: true, raw: true, deadEnd: false };
  if (status === "notfound") {
    return {
      overview: hasCardOverview,
      raw: hasRawSlice,
      deadEnd: !hasCardOverview && !hasRawSlice,
    };
  }
  return { overview: false, raw: false, deadEnd: false };
}

export default function DeepDiveView({ domainKey, overview, state }) {
  const [payload, setPayload] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | notfound | error
  const [tab, setTab] = useState("overview");

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const r = await apiFetch(`/api/deep/${domainKey}`);
      if (r.status === 404) {
        setStatus("notfound");
        return;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setPayload(await r.json());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, [domainKey]);

  useEffect(() => {
    load();
  }, [load]);

  // A provider-less domain still has a live slice in state.json for most domains;
  // when so, the deep-dive falls back to the Raw-signal tree rather than a blank.
  const hasRawSlice = useMemo(() => Boolean(sliceFor(domainKey, state)), [domainKey, state]);
  const CardOverview = CARD_OVERVIEW[domainKey];
  const mode = panelMode(status, hasRawSlice, Boolean(CardOverview));

  // Land on Raw signal when that's the only populated tab (no curated overview).
  useEffect(() => {
    if (mode.raw && !mode.overview) setTab("raw");
  }, [mode.raw, mode.overview]);

  // Esc returns to the dashboard — full-page views should be dismissible.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") navigate("");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const label = payload?.label || titleCase(domainKey);
  // Provider status when there is one; else the domain's rolled-up status from the
  // overview, so a card-Overview section still lights its header pill correctly.
  const st =
    payload?.status ||
    (overview?.domains || []).find((d) => d.key === domainKey)?.status ||
    "unknown";
  const Bespoke = BESPOKE[domainKey];
  const suggestions = payload?.manifest?.suggestions;

  return (
    <div className="deepdive">
      <header className="dv-head">
        <button className="dv-back" onClick={() => navigate("")} aria-label="Back to dashboard">
          <span aria-hidden="true">←</span> Command Center
        </button>
        <div className="dv-head-title">
          <span className="eyebrow">Deep dive</span>
          <h1 className="dv-title t-title">{label}</h1>
        </div>
        <div className="dv-head-right">
          <span className={`dv-status ${statusClass(st)}`} title="section status">
            <span className="dv-status-dot" aria-hidden="true" />
            {st}
          </span>
          <button className="dv-refresh" onClick={load} aria-label="Refresh section" title="Refresh">
            ↻
          </button>
        </div>
      </header>

      <div className="dv-body">
        <main className="dv-content">
          <nav className="dv-tabs" aria-label="Deep-dive views">
            <button
              className={`dv-tab${tab === "overview" ? " is-active" : ""}`}
              onClick={() => setTab("overview")}
              aria-pressed={tab === "overview"}
            >
              Overview
            </button>
            <button
              className={`dv-tab${tab === "raw" ? " is-active" : ""}`}
              onClick={() => setTab("raw")}
              aria-pressed={tab === "raw"}
            >
              Raw signal
            </button>
          </nav>

          <div className="dv-panel">
            {status === "loading" && (
              <div className="dv-state t-caption">Reading the substrate…</div>
            )}
            {mode.deadEnd && (
              <div className="dv-state">
                <p className="dv-state-lede">No deep-dive for this section yet.</p>
                <p className="t-caption">
                  It still answers in the substrate console — ask the supervisor on the right.
                </p>
              </div>
            )}
            {status === "error" && (
              <div className="dv-state">
                <p className="dv-state-lede">Couldn’t load this section.</p>
                <button className="dv-retry" onClick={load}>Try again</button>
              </div>
            )}

            {mode.overview && tab === "overview" && (
              status === "ready"
                ? (Bespoke ? <Bespoke payload={payload} /> : <GenericDeepDive payload={payload} />)
                : <CardOverview state={state} status={st} />
            )}
            {!mode.overview && mode.raw && tab === "overview" && (
              <div className="dv-state">
                <p className="dv-state-lede">No curated overview for this section yet.</p>
                <p className="t-caption">
                  Its live raw signal is one tab over — or ask the supervisor on the right.
                </p>
              </div>
            )}
            {mode.raw && tab === "raw" && (
              <RawSignal domainKey={domainKey} state={state} summary={payload?.manifest?.lede} />
            )}
          </div>
        </main>

        <aside className="dv-dock" aria-label="Scoped supervisor">
          <SupervisorChat
            overview={overview}
            variant="dock"
            scope={{ domain: domainKey, label }}
            suggestions={suggestions}
          />
        </aside>
      </div>
    </div>
  );
}

function titleCase(s) {
  return (s || "").replace(/(^|[-_])(\w)/g, (_, __, c) => " " + c.toUpperCase()).trim();
}
