/**
 * Runtime API-base shim — load this FIRST, before any module that issues
 * network requests.
 *
 * Why it exists
 * -------------
 * The PWA build (served same-origin by FastAPI) uses RELATIVE `/api/...` paths,
 * so they resolve against the page origin and hit the backend directly.
 *
 * The Tauri build loads its bundled assets from a LOCAL origin
 * (`tauri://localhost` on macOS, `http://tauri.localhost` on Linux). There,
 * `/api/...` would resolve to that local origin and never reach the backend.
 * The monarch backend lives on the monarch box and is reachable only over
 * Tailscale, so inside Tauri we rewrite every `/api` request to the absolute
 * backend base.
 *
 * Security note: this is the seam that keeps the privileged webview content
 * fully local/immutable while only JSON crosses the wire. The CSP `connect-src`
 * directive pins exactly this one backend origin; if you change the endpoint
 * here you must change it in `desktop/src-tauri/tauri.conf.json` too.
 */

import { normalizeBase, rewriteApiPath } from "./urlRewrite.js";

// The backend endpoint (the monarch substrate over Tailscale) is supplied at
// BUILD time via VITE_API_BASE — never hardcoded in source, so the repo carries
// no infrastructure details. The desktop build script reads it from a gitignored
// `desktop/.env` (see desktop/.env.example). Vite inlines it here at build time.
const CONFIGURED_BASE = import.meta.env?.VITE_API_BASE || "";

// Rewrite ONLY when the page is served from Tauri's bundled-asset origin
// (`tauri://localhost` on macOS, `http://tauri.localhost` on Linux/Windows) —
// i.e. a production desktop bundle. In Tauri *dev* mode the page loads from the
// Vite dev server (`devUrl`), which already proxies /api to a local backend, so
// we leave requests relative there. The browser PWA never matches either.
const onBundledAssetOrigin =
  typeof window !== "undefined" &&
  (window.location.protocol === "tauri:" ||
    window.location.hostname === "tauri.localhost");

if (onBundledAssetOrigin && !CONFIGURED_BASE) {
  // Bundled desktop app with no backend baked in — /api would resolve to the
  // local asset origin and fail. Surface it loudly rather than silently break.
  console.error(
    "[command-center] No VITE_API_BASE was set at build time; the desktop app " +
      "has no backend endpoint. Rebuild via the desktop build script with " +
      "desktop/.env configured (see desktop/.env.example)."
  );
}

const RAW_BASE = onBundledAssetOrigin ? CONFIGURED_BASE : "";

export const API_BASE = normalizeBase(RAW_BASE);

/** Rewrite app-API paths to the absolute backend; leave local assets alone. */
function absolutize(url) {
  return rewriteApiPath(url, API_BASE);
}

if (API_BASE) {
  // --- fetch ---------------------------------------------------------------
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    if (typeof input === "string") {
      return nativeFetch(absolutize(input), init);
    }
    if (input instanceof Request) {
      try {
        const u = new URL(input.url, window.location.origin);
        if (u.pathname === "/api" || u.pathname.startsWith("/api/")) {
          return nativeFetch(
            new Request(API_BASE + u.pathname + u.search, input)
          );
        }
      } catch {
        /* fall through to the unmodified request */
      }
    }
    return nativeFetch(input, init);
  };

  // --- EventSource (SSE /api/stream) --------------------------------------
  const NativeES = window.EventSource;
  if (NativeES) {
    const PatchedES = function (url, config) {
      return new NativeES(absolutize(url), config);
    };
    PatchedES.prototype = NativeES.prototype;
    PatchedES.CONNECTING = NativeES.CONNECTING;
    PatchedES.OPEN = NativeES.OPEN;
    PatchedES.CLOSED = NativeES.CLOSED;
    window.EventSource = PatchedES;
  }
}
