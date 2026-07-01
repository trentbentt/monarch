// Load FIRST: rewrites /api requests to the absolute backend when running
// inside the Tauri desktop shell (no-op in the browser PWA).
import "./runtime/apiBase.js";

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
}
