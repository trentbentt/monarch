import { useState, lazy, Suspense } from "react";
import { useLiveState } from "./hooks/useLiveState.js";
import { useHashRoute } from "./hooks/useHashRoute.js";
import { useReachabilityAlert } from "./hooks/useReachabilityAlert.js";
import DeepDiveView from "./components/deep/DeepDiveView.jsx";
import LightningBackground from "./components/shell/LightningBackground.jsx";
import AttentionList from "./components/AttentionList.jsx";
import RichGrid from "./components/RichGrid.jsx";
import PendingPanel from "./components/PendingPanel.jsx";
import MemoryQueues from "./components/MemoryQueues.jsx";
import DocsSearch from "./components/DocsSearch.jsx";
import PushControls from "./components/PushControls.jsx";
import ControlPanel from "./components/ControlPanel.jsx";
import ConfirmModal from "./components/ConfirmModal.jsx";
import IntroErrorBoundary from "./components/IntroErrorBoundary.jsx";
import IntroCover from "./components/IntroCover.jsx";
import SideRail from "./components/shell/SideRail.jsx";
import Spotlight from "./components/shell/Spotlight.jsx";
import SupervisorChat from "./components/SupervisorChat.jsx";

// The 3D intro is heavy (Three.js + brain meshes) — lazy-load it so it never
// touches the dashboard/phone bundle. Desktop-only, once per session.
const IntroSequence = lazy(() => import("./components/IntroSequence.jsx"));

function UnreachableBanner({ alerting, offlineForMs }) {
  if (!alerting) return null;
  const mins = Math.max(1, Math.round(offlineForMs / 60000));
  return (
    <div className="stale-banner unreachable-banner" role="alert">
      ⛔ Can’t reach monarch for ~{mins} min — the box may be down (power loss or
      network). Showing last-known state.
    </div>
  );
}

function StaleBanner({ overview }) {
  if (!overview?.stale) return null;
  const age = overview.state_age_sec ? Math.round(overview.state_age_sec) : null;
  return (
    <div className="stale-banner">
      ⚠ Showing last-known state{age != null ? ` (${age}s old)` : ""} — monarch / Loki
      daemon may be unreachable or stalled.
    </div>
  );
}

function Console({ overview, state, routing, pending, conn, confirm, setConfirm, reach }) {
  // Chat is collapsed natively so the bento gets the room; the operator opens it
  // to talk. Preference persists across reloads.
  const [chatOpen, setChatOpen] = useState(() => localStorage.getItem("cc:chat-open") === "1");
  const toggleChat = () => {
    setChatOpen((v) => {
      const next = !v;
      localStorage.setItem("cc:chat-open", next ? "1" : "0");
      return next;
    });
  };

  return (
    <div className={`console${chatOpen ? "" : " chat-collapsed"}`}>
      <SideRail overview={overview} conn={conn} />

      <main className="console-main">
        <UnreachableBanner alerting={reach?.alerting} offlineForMs={reach?.offlineForMs} />
        <StaleBanner overview={overview} />

        <section className="attention-strip">
          <div className="eyebrow">Needs attention</div>
          <AttentionList attention={overview.attention} />
        </section>

        <Spotlight className="bento-wrap">
          <RichGrid overview={overview} state={state} />
        </Spotlight>

        <section className="ops">
          <PendingPanel pending={pending} openConfirm={setConfirm} />
          <ControlPanel openConfirm={setConfirm} />
          <div className="ops-row">
            <MemoryQueues />
            <PushControls />
          </div>
          <DocsSearch />
        </section>

        <footer className="foot">
          <span>updated {overview.last_updated || "—"}</span>
          <span>routing {routing?.summary || "—"}</span>
        </footer>
      </main>

      <SupervisorChat overview={overview} collapsed={!chatOpen} onToggle={toggleChat} />

      {confirm && (
        <ConfirmModal
          action={confirm.action}
          params={confirm.params}
          label={confirm.label}
          danger={confirm.danger}
          onClose={() => setConfirm(null)}
          onDone={(res) => confirm.onDone && confirm.onDone(res)}
        />
      )}
    </div>
  );
}

export default function App() {
  const { overview, state, routing, pending, conn } = useLiveState();
  const reach = useReachabilityAlert(conn);
  const [confirm, setConfirm] = useState(null);
  const route = useHashRoute();

  // Decide synchronously (frame 1) so the entrance cover is painted before the
  // dashboard ever renders — no flash of the dashboard behind a delayed loader.
  const [showIntro, setShowIntro] = useState(() => {
    if (typeof window === "undefined") return false;
    const desktop = window.matchMedia("(min-width: 768px)").matches;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const seen = sessionStorage.getItem("cc:intro-seen");
    return desktop && !reduced && !seen;
  });

  const endIntro = () => {
    sessionStorage.setItem("cc:intro-seen", "1");
    setShowIntro(false);
  };

  const intro = showIntro ? (
    <IntroErrorBoundary onError={endIntro}>
      <Suspense fallback={<IntroCover />}>
        <IntroSequence onComplete={endIntro} />
      </Suspense>
    </IntroErrorBoundary>
  ) : null;

  // While the entrance plays, render ONLY the intro — never mount the heavy live
  // console behind it. The intro is a real-time Three.js scene; it gets the whole
  // main thread + GPU. The console mounts the moment the intro completes.
  if (showIntro) {
    return (
      <>
        <div className="aurora-bg" aria-hidden="true" />
        {intro}
      </>
    );
  }

  if (!overview) {
    return (
      <>
        <div className="aurora-bg" aria-hidden="true" />
        <div className="app loading">
          <span className={`conn conn-${conn}`}>{conn}</span>
          <p>Connecting to monarch…</p>
          <UnreachableBanner alerting={reach.alerting} offlineForMs={reach.offlineForMs} />
        </div>
        {intro}
      </>
    );
  }

  // A card opened its full-page deep-dive (#/deep/<key>) — take over the whole
  // viewport with the scoped supervisor docked alongside. Back/Esc returns home.
  if (route.name === "deep" && route.key) {
    return (
      <>
        <div className="aurora-bg" aria-hidden="true" />
        <LightningBackground intensity={0.5} />
        <DeepDiveView key={route.key} domainKey={route.key} overview={overview} state={state} />
        {intro}
      </>
    );
  }

  return (
    <>
      <div className="aurora-bg" aria-hidden="true" />
      <LightningBackground intensity={0.5} />
      <Console
        overview={overview}
        state={state}
        routing={routing}
        pending={pending}
        conn={conn}
        confirm={confirm}
        setConfirm={setConfirm}
        reach={reach}
      />
      {intro}
    </>
  );
}
