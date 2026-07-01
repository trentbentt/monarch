import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { fileURLToPath, URL } from "node:url";

// Dev proxies /api to the FastAPI backend (loopback). In prod the PWA is served
// same-origin (over Tailscale), so the same relative /api paths resolve.
//
// VITE_TAURI=1 builds the bundle for the native Tauri desktop shell: the
// service worker / PWA install path is omitted (the webview loads bundled local
// assets, not a network origin, so there is nothing to install or precache),
// and apiBase.js rewrites /api to the absolute backend at runtime.
const isTauri = process.env.VITE_TAURI === "1";

export default defineConfig({
  // The ported neuro 3D intro lives under src/intro and uses "@/..." imports.
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src/intro", import.meta.url)),
    },
  },
  plugins: [
    react(),
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
        // The heavy 3D intro chunk + brain meshes load on demand (desktop, once
        // per session) — keep them out of the install-time precache.
        globIgnores: ["**/IntroSequence-*.js", "**/IntroSequence-*.css"],
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
      // Defaults to the prod backend port; override with CC_API_TARGET to point
      // a dev server at an alternate backend (e.g. a redesign preview instance).
      "/api": { target: process.env.CC_API_TARGET || "http://127.0.0.1:8770", changeOrigin: true },
    },
  },
});
