import { useState, lazy, Suspense } from "react";
import { useLiveState } from "./hooks/useLiveState.js";
import { useHashRoute } from "./hooks/useHashRoute.js";
import { usePhone } from "./hooks/usePhone.js";
import TabBar from "./components/shell/TabBar.jsx";
import { useTabs } from "./components/shell/useTabs.js";
import { useReachabilityAlert } from "./hooks/useReachabilityAlert.js";
import DeepDiveView from "./components/deep/DeepDiveView.jsx";
import GapsView from "./components/deep/GapsView.jsx";
import AtlasView from "./components/anatomy/AtlasView.jsx";
import LightningBackground from "./components/shell/LightningBackground.jsx";
import AttentionList from "./components/AttentionList.jsx";
import UpdateNote from "./components/UpdateNote.jsx";
import UpdateCheck from "./components/UpdateCheck.jsx";
import RichGrid from "./components/RichGrid.jsx";
import PendingPanel from "./components/PendingPanel.jsx";
import DigestCard from "./components/DigestCard.jsx";
import MemoryQueues from "./components/MemoryQueues.jsx";
import DocsSearch from "./components/DocsSearch.jsx";
import PushControls from "./components/PushControls.jsx";
import ControlPanel from "./components/ControlPanel.jsx";
import ConfirmModal from "./components/ConfirmModal.jsx";
import IntroErrorBoundary from "./components/IntroErrorBoundary.jsx";
import IntroCover from "./components/IntroCover.jsx";
import SideRail from "./components/shell/SideRail.jsx";
import LoadingGate from "./components/LoadingGate.jsx";
import Spotlight from "./components/shell/Spotlight.jsx";
import SupervisorChat from "./components/SupervisorChat.jsx";
import TerminalDock from "./components/terminal/TerminalDock.jsx";

// The 3D intro is heavy (Three.js + brain meshes) — lazy-load it so it never
// touches the dashboard/phone bundle. Desktop-only, once per session.
const IntroSequence = lazy(() => import("./components/IntroSequence.jsx"));

// World view rides the same heavy-chunk policy as the intro (three.js).
const WorldView = lazy(() => import("./components/world/WorldView.jsx"));

/**
 * Shown when monarch answered 401 — the read-gate is armed and this client has
 * no valid token. Deliberately distinct from UnreachableBanner: the box is UP,
 * and the fix is pairing, not checking the power. Exported for test.
 */
export function UnpairedBanner({ conn }) {
  if (conn !== "unauthorized") return null;
  return (
    <div className="stale-banner unpaired-banner" role="alert">
      🔒 Not paired — monarch is up but this device has no control token. Open
      <strong> Control</strong> and paste the token to restore live data.
    </div>
  );
}

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
        <UnpairedBanner conn={conn} />
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
          <DigestCard openConfirm={setConfirm} />
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

  // Tabs are desktop-only, matching how TerminalDock is already gated: the
  // phone keeps its single-view stack, where a horizontal strip of nine
  // targets would cost more room than it navigates (IA §7).
  const phone = usePhone();
  const tabs = useTabs(route, { enabled: !phone });

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

  // No state yet. If the reason is AUTHORIZATION, this must offer pairing —
  // the console (which owns ControlPanel) never mounts without `overview`, so
  // under the armed read-gate a fresh unpaired client would otherwise be locked
  // out permanently: 401 forever, no way to enter the token.
  if (!overview) {
    return (
      <>
        <div className="aurora-bg" aria-hidden="true" />
        <LoadingGate
          conn={conn}
          reach={reach}
          onConfirm={setConfirm}
          Banner={UnpairedBanner}
          Unreachable={UnreachableBanner}
        />
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
        {intro}
      </>
    );
  }

  // Route content is computed, not early-returned, so the terminal dock
  // below occupies the SAME tree position on every desktop route — a route
  // switch reconciles around it instead of remounting it, which is what
  // keeps the attached session (xterm + WebSocket) alive across
  // home ↔ Atlas ↔ World ↔ deep-dive navigation.
  let content;
  if (route.name === "deep" && route.key) {
    // A card opened its full-page deep-dive (#/deep/<key>) — take over the
    // whole viewport with the scoped supervisor docked alongside. Back/Esc
    // returns home.
    content = (
      <>
        <div className="aurora-bg" aria-hidden="true" />
        <LightningBackground intensity={0.5} />
        {route.key === "gaps"
          ? <GapsView key="gaps" />
          : <DeepDiveView key={route.key} domainKey={route.key} overview={overview} state={state} />}
      </>
    );
  } else if (route.name === "anatomy") {
    // Atlas (#/anatomy) — full-viewport system anatomy. Back/Esc returns home.
    content = (
      <>
        <div className="aurora-bg" aria-hidden="true" />
        <LightningBackground intensity={0.5} />
        <AtlasView overview={overview} nodeId={route.key} />
      </>
    );
  } else if (route.name === "world") {
    content = (
      <Suspense fallback={<div className="world world-loading">Entering the world…</div>}>
        <WorldView nodeId={route.key} />
      </Suspense>
    );
  } else {
    content = (
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
      </>
    );
  }

  return (
    <>
      {/* Above the view and outside `content`, so a route switch reconciles
          the bar in place rather than remounting it — the same reason the
          terminal dock holds a fixed tree position. */}
      {!phone && (
        <TabBar
          tabs={tabs.tabs}
          activeKey={tabs.activeKey}
          labels={Object.fromEntries(
            (overview?.domains || []).map((d) => [d.key, d.label]))}
          onFocus={tabs.focus}
          onClose={tabs.close}
        />
      )}
      {content}
      <TerminalDock />
      {/* Reached only after the intro (showIntro early-returns above) — the
          desktop "updated to vX" note can never appear during the entrance. */}
      {!showIntro && <UpdateNote />}
      {/* M50: manual update check, desktop shell only (renders null in the
          PWA). Lives in the same corner chrome as the note it produces. */}
      {!showIntro && <UpdateCheck />}
      {intro}
    </>
  );
}
