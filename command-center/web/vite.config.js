import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { fileURLToPath, URL } from "node:url";
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";

// Build stamp. Nothing in the running system used to expose which build it was,
// so "did the update land?" could only be answered by comparing file mtimes
// against commit timestamps — which is exactly how a stale desktop bundle went
// unnoticed for a day and a half. The bundle now carries its own identity and
// the UI compares it against the server's.
function stamp(name, fn, fallback = "unknown") {
  try { return fn() || fallback; } catch { return fallback; }
}
// Three sources, in order of authority. The macOS bundle is built on the Mac
// from a tree DELIVERED BY RSYNC (Apple's toolchain cannot run on the Linux
// box), and that tree deliberately carries no .git — so `git rev-parse` there
// returns nothing and the stamp fell back to "unknown". A client that cannot
// name its own build makes the sync verdict permanently read "cannot confirm",
// which disables the one indicator built to answer "did the update land?".
//
//   1. git          — a normal checkout, the usual case
//   2. CC_BUILD_SHA — explicit override, for a scripted build
//   3. .build-sha   — written into the tree by scripts/sync-to-mac.sh, so a
//                     delivered tree describes itself without needing history
const SHA_FILE = new URL("../.build-sha", import.meta.url);
const BUILD_SHA = stamp("sha", () => {
  try {
    return execSync("git rev-parse --short HEAD",
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return (process.env.CC_BUILD_SHA
      || readFileSync(SHA_FILE, "utf8")).trim();
  }
});
// The sha names a COMMIT; nothing above says whether the tree actually MATCHED
// it. A bundle built with uncommitted changes carries the sha of content it
// does not have — and every downstream verdict trusts that sha (asset_sha
// match, commits-behind 0), so the unreproducible bundle reads GREEN at HEAD
// (M57). The dirty bit is measured here, at the one moment the builder can
// see the tree.
//
// When git is unavailable (the rsync-delivered mac tree carries no .git), the
// bit is UNMEASURED: null, never false. A fabricated "clean" is a claim without
// evidence, in exactly the direction that hides the defect — that lane is
// instead guarded at its door, where sync-to-mac.sh refuses to deliver a dirty
// tree. CC_BUILD_DIRTY=0|1 lets a scripted build that measured its own tree
// say so, the same escape hatch CC_BUILD_SHA provides for the sha.
// The measure is SCOPED to the bundle's inputs — web/ plus the version's source
// file — and to TRACKED modifications (-uno, `git describe --dirty` semantics:
// untracked files are invisible to a checkout, so they are not content the sha
// claims). Whole-repo porcelain was the first cut and was wrong in this estate:
// several sessions run at once, so someone's uncommitted server/ or scripts/
// edit — content that never enters this bundle — would stamp every build dirty,
// and a chronically-red bit is noise the operator learns to ignore, which
// un-builds the guard (the M22 shape). A modified tracked file INSIDE web/ is
// bundle input and fires correctly, whoever owns it.
const BUILD_DIRTY = (() => {
  try {
    // M137: `.` is web/, and 50 of its 230 tracked files are tests that vite
    // never bundles. Measured 2026-08-03: a commit changing only
    // src/deepdive2.test.jsx marked the bundle stale, while no describe() token
    // from it and no "deepdive2" string appears anywhere in dist/assets/*.js.
    // A dirty bit that fires for content which cannot reach the artifact is
    // the same cry-wolf failure the comment above rejects whole-repo porcelain
    // for — M57's own principle (scope a dirty measure to the ARTIFACT'S
    // INPUTS), applied to the one part of web/ that is not one.
    return execSync(
      "git status --porcelain -uno -- . ':(exclude)**/*.test.js' ':(exclude)**/*.test.jsx' ':(exclude)**/*.test.mjs' ':(exclude)e2e/**' ../desktop/src-tauri/tauri.conf.json",
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim().length > 0;
  } catch {
    if (process.env.CC_BUILD_DIRTY === "1") return true;
    if (process.env.CC_BUILD_DIRTY === "0") return false;
    return null;
  }
})();
// ONE version for the product, read from the one file that is authoritative for
// it: tauri.conf.json drives the updater AND is what server/buildinfo.py
// reports. Reading web/package.json here made the version live in two places,
// and they drifted immediately — the stamp showed "web 0.1.0 / server 0.1.7",
// which reads as a fault when nothing is actually wrong. package.json's version
// stays npm metadata; nothing user-facing consumes it.
const VERSION_FILE = new URL("../desktop/src-tauri/tauri.conf.json", import.meta.url);
const BUILD_VERSION = stamp("version", () =>
  JSON.parse(readFileSync(VERSION_FILE, "utf8")).version);
// Same number, surfaced under the "desktop" label when building the Tauri shell
// — that is the value its updater compares against the feed.
const DESKTOP_VERSION = process.env.VITE_TAURI === "1" ? BUILD_VERSION : "";

// Dev proxies /api to the FastAPI backend (loopback). In prod the PWA is served
// same-origin (over Tailscale), so the same relative /api paths resolve.
//
// VITE_TAURI=1 builds the bundle for the native Tauri desktop shell: the
// service worker / PWA install path is omitted (the webview loads bundled local
// assets, not a network origin, so there is nothing to install or precache),
// and apiBase.js rewrites /api to the absolute backend at runtime.
const isTauri = process.env.VITE_TAURI === "1";

// Emit the stamp as a FILE alongside the bundle, not only as a `define` baked
// into minified JS. The server has to be able to answer "what am I serving?",
// and the only way to get that out of the bundle otherwise is to grep a 7-hex
// string out of minified output — which matches any hash-like token and is not
// something to build a health indicator on.
//
// This is what makes the sync verdict meaningful: the client compares its own
// sha against the sha of the bundle THE SERVER IS SERVING, rather than against
// whatever commit the server process happened to boot at. Those are different
// questions, and comparing against the wrong one made the indicator read
// "mismatch" after any commit while failing to notice web/dist sitting four
// days stale (2026-07-27).
function buildStampFile() {
  return {
    name: "cc-build-stamp",
    apply: "build",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "build-stamp.json",
        source: JSON.stringify({
          sha: BUILD_SHA,
          // true/false when measured; null when the builder had no git and
          // nothing vouched for the tree. Readers must treat null as absent.
          dirty: BUILD_DIRTY,
          version: BUILD_VERSION,
          builtAt: new Date().toISOString(),
          tauri: isTauri,
        }, null, 2) + "\n",
      });
    },
  };
}

export default defineConfig({
  define: {
    __BUILD_SHA__: JSON.stringify(BUILD_SHA),
    __BUILD_VERSION__: JSON.stringify(BUILD_VERSION),
    __DESKTOP_VERSION__: JSON.stringify(DESKTOP_VERSION),
  },
  // The ported neuro 3D intro lives under src/intro and uses "@/..." imports.
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src/intro", import.meta.url)),
    },
  },
  plugins: [
    react(),
    buildStampFile(),
    !isTauri &&
    VitePWA({
      registerType: "autoUpdate",
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.js",
      includeAssets: ["favicon.svg"],
      injectManifest: {
        // /api/* is dynamic; only precache the built app shell.
        globPatterns: ["**/*.{js,css,html,svg}"],
        // The heavy intro + world 3D runtime chunks load on demand (desktop,
        // once per session) — keep them out of the install-time precache.
        globIgnores: ["**/IntroSequence-*.js", "**/IntroSequence-*.css", "**/three-*.js"],
        maximumFileSizeToCacheInBytes: 600 * 1024,
      },
      manifest: {
        name: "Monarch Command Center",
        short_name: "Monarch",
        description: "Monarch sovereign AI substrate — operator console",
        theme_color: "#04040F",
        background_color: "#04040F",
        display: "standalone",
        start_url: "/",
        scope: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
          { src: "app-icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
        ],
      },
    }),
  ],
  server: {
    // Dev server binds all interfaces so it's reachable over Tailscale during
    // local development. (Prod posture stays loopback + Tailscale; the FastAPI
    // backend it proxies to remains 127.0.0.1-only.)
    host: true,
    proxy: {
      // Defaults to the prod backend port — 8780, which is what
      // command-center.service actually binds (`uvicorn main:app --port 8780`)
      // and what `tailscale serve :8443` proxies to. This read 8770 for a long
      // while, so `npm run dev` proxied into a dead port and every /api call in
      // the dev server 502'd. Override with CC_API_TARGET to point a dev server
      // at an alternate backend (e.g. a redesign preview instance).
      "/api": { target: process.env.CC_API_TARGET || "http://127.0.0.1:8780", changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      // Both the browser/PWA and the Tauri desktop build bundle the WHOLE app
      // from index.html. The only Tauri difference is the PWA/service-worker is
      // omitted (above); apiBase.js rewrites /api to the tailnet backend at
      // runtime by inspecting the origin, so one bundle serves both surfaces.
      output: {
        manualChunks: {
          // Shared 3D runtime (intro + world). Loaded on demand, never precached.
          three: ["three", "@react-three/fiber", "@react-three/drei"],
        },
      },
    },
  },
});
