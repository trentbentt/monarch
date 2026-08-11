// Load FIRST: rewrites /api requests to the absolute backend when running
// inside the Tauri desktop shell (no-op in the browser PWA).
import "./runtime/apiBase.js";

// Reload once when a new service worker takes control. registerType
// "autoUpdate" generated only a bare register() call — nothing implemented
// the update half — so a new worker parked forever and shipped fixes never
// reached the phone. sw.js now activates immediately; this brings the PAGE
// onto the matching bundle instead of leaving old JS against a new cache.
import { installSwReload } from "./runtime/swReload.js";
installSwReload();

import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
// Self-hosted faces — the Monarch voice: Fraunces (elegant variable serif, the
// display/brand face) over Geist (crisp high-grade-tech body) and Geist Mono
// (instrument readouts). Classy, electric, and highly legible.
import "@fontsource-variable/fraunces";
import "@fontsource/geist-sans/300.css";
import "@fontsource/geist-sans/400.css";
import "@fontsource/geist-sans/500.css";
import "@fontsource/geist-sans/600.css";
import "@fontsource/geist-mono/400.css";
import "@fontsource/geist-mono/500.css";
import "./design/tokens.css";
import "./design/primitives/primitives.css";
import "./styles.css";
import "./design/shell.css";
// LAST: iPhone-tailored mobile pass — overrides the desktop shell at phone
// widths and for touch pointers (safe areas, stacked deep-dive, finger targets).
import "./styles.mobile.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Desktop only: drive native OS notifications off the live SSE stream. Loaded
// lazily and gated on the Tauri runtime so the browser PWA never pulls it in.
if (typeof window !== "undefined" && window.__TAURI_INTERNALS__) {
  import("./runtime/nativeNotify.js")
    .then((m) => m.startNativeNotifier())
    .catch(() => {});

  // Desktop auto-update (G7 + M50): deferred so it never competes with the
  // intro's first paint / three.js chunk. Checks at launch AND on a standing
  // interval — the app is chrome the operator leaves open for days, and a
  // once-per-launch check meant "next launch" never came and a long-lived
  // session never updated. Downloads + installs silently and applies on the
  // NEXT launch — the running session and its intro are untouched.
  const _kickUpdate = () =>
    import("./runtime/desktopUpdate.js").then((m) => m.default()).catch(() => {});
  if ("requestIdleCallback" in window) requestIdleCallback(_kickUpdate);
  else setTimeout(_kickUpdate, 4000);
}
