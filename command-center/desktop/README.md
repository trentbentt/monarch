# Monarch Command Center — Desktop (Tauri)

A native desktop client for the Command Center, for **macOS** and **Linux**. It
renders the operator console in the OS's own webview (WebKit — *not* Chromium, so
no Chrome/Edge engine is involved) and reaches the monarch substrate over
Tailscale. It fires **native OS notifications** on interrupt-class events while
running.

It is a *thin client*: the brain never leaves the monarch box. The FastAPI
backend stays loopback-bound on monarch.

## How it works: fully-bundled app, live data

The app is **fully bundled**. It ships the whole console (`index.html`), plays
the intro locally, and reveals the dashboard in the **same document** on Enter —
no navigation, no download. Only JSON crosses the wire:

```
┌─ Monarch Command Center.app ─────────┐        monarch box
│  index.html  (BUNDLED, local)        │        ┌──────────────────────────┐
│   1. plays the intro (local, GPU)    │        │ tailscale serve :8443    │
│   2. Enter → reveals the dashboard   │        │   → FastAPI 127.0.0.1:8770│
│      (already loaded, instant)       │        │     (loopback only)      │
│   • fetch/SSE → /api ────────────────┼──────► │                          │
│   • SSE → native OS notifications    │ tailnet└──────────────────────────┘
└──────────────────────────────────────┘  only  (JSON only — no remote code)
```

`useLiveState` opens its SSE/poll on mount — i.e. **while the intro plays** — so
by the time Enter is pressed the data is already flowing and the dashboard
reveals populated. `apiBase.js` rewrites `/api` to the tailnet backend at runtime
by inspecting the bundled-asset origin; the same bundle serves the browser PWA
(where `/api` stays relative).

Trade-off: desktop **frontend-code** updates need a rebuild + reinstall, because
the UI is snapshot into the app. The browser/PWA stays instantly-updating for
day-to-day dev, and data is always live in both. (This restores the original
bundled model, reversing the 2026-07-20 hybrid that streamed the console live but
cost the smooth intro→reveal.)

## Security posture

**Full webview isolation.** The webview renders **only** bundled local assets;
no remote origin is ever navigable, so a compromised backend cannot inject code
into the privileged webview — it can only feed it JSON, which the app treats as
data. (This restores the isolation the 2026-07-20 hybrid had traded away.)

| Surface | Hardening |
| --- | --- |
| Webview content | **Bundled local assets only.** No remote origin is renderable, so backend responses are data (JSON), never code. |
| Navigation | A Rust `on_navigation` guard (`src-tauri/src/lib.rs`) allows **only** Tauri's local origins and refuses **every** remote origin — including credential-smuggling (`https://tauri.localhost@evil.com`) and lookalike hosts. Unit-tested. |
| CSP | `default-src 'self'` with `connect-src` narrowed at build time to `'self'` + exactly the backend origin (fetch/SSE only). `script-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`. |
| No infra in source | The backend origin is **never committed** — injected at build from a gitignored `desktop/.env` into `apiBase.js` (via `VITE_API_BASE`) and the CSP `connect-src`. The repo carries zero infrastructure details. |
| Capabilities | Minimal: `core:default` + `notification:default` on the local main window (`capabilities/default.json`). **No** shell, fs, http, dialog, or clipboard access. Because the window never leaves the local origin, this covers native notifications — no remote capability exists. |
| IPC surface | `withGlobalTauri: false`; no custom commands are exposed to JS. |
| Transport | Tailnet-only HTTPS (`:8443` is *not* internet-funneled). Backend bind stays `127.0.0.1`. |
| Binary | Release profile strips symbols and aborts on panic. |

The backend origin lives in exactly one place — `desktop/.env` (gitignored) —
and `scripts/build-desktop.sh` fans it out to both consumers (`VITE_API_BASE` in
`apiBase.js` and the CSP `connect-src`). Change it there only. An explicit
`CC_DESKTOP_API_BASE=... npm run build` overrides the file.

### Failure modes

The intro and the dashboard are the same bundled document, so a broken intro
never strands the operator — it simply reveals the (already-loaded) dashboard:

- intro **throws** (WebGL/asset failure) → `IntroErrorBoundary` (in `App.jsx`)
  ends the intro and shows the dashboard.
- backend **unreachable** → the dashboard renders from last-known/empty state
  with an in-app "Can't reach monarch" banner; SSE/poll reconnects automatically.

## Prerequisites

- **Rust** (stable): `curl https://sh.rustup.rs -sSf | sh`
- **Node** 18+
- **Linux only** — system libraries:
  ```bash
  sudo apt install -y libwebkit2gtk-4.1-dev build-essential curl wget file \
    libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev \
    libgtk-3-dev libsoup-3.0-dev
  ```
- **macOS only** — Xcode Command Line Tools: `xcode-select --install`

## Build

```bash
# from desktop/
cp .env.example .env        # then edit .env: set CC_DESKTOP_API_BASE to your backend
npm install                 # Tauri CLI
npm run icons               # (once) generate app icons from ../web/public/icon-512.png
npm run build               # frontend (with endpoint baked in) then bundles the app
```

`npm run build` runs `scripts/build-desktop.sh`, which reads `desktop/.env`,
builds the full app bundle (`index.html`) with the endpoint baked into
`apiBase.js`, removes any stale remote capability, and runs `tauri build` with
the CSP `connect-src` narrowed to that origin. Outputs land in
`src-tauri/target/release/bundle/`:
- **Linux**: `.deb` and `.AppImage`
- **macOS**: `.app` and `.dmg`

Pass bundle selectors through, e.g. skip RPM on a host without `rpmbuild`:
`npm run build -- --bundles deb,appimage`.

### Containerized Linux build (no host sudo)

If you can't install the system libraries on the host (e.g. no sudo), build the
Linux bundles in a container. `Dockerfile.build` carries the system libs; the
host's Rust toolchain + warmed crate cache + the host-built `web/dist-tauri` are
mounted in:

```bash
# from desktop/ (with .env configured)
docker build -f Dockerfile.build -t cc-tauri-builder .
docker run --rm --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e RUSTUP_HOME="$HOME/.rustup" -e CARGO_HOME="$HOME/.cargo" \
  -e PATH="$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin" \
  -v "$(cd .. && pwd)":/work -v "$HOME/.cargo":"$HOME/.cargo" -v "$HOME/.rustup":"$HOME/.rustup" \
  -w /work/desktop cc-tauri-builder \
  bash scripts/build-desktop.sh --bundles deb,appimage
```

The script reads `desktop/.env` (mounted in) and injects the endpoint + CSP, so
the container build carries the same hardening as a host build. Artifacts land in
`src-tauri/target/release/bundle/` on the host. The image also carries
`xvfb`/`dbus-x11` so the binary can be headless smoke-tested.

### Dev

```bash
npm run dev    # launches the app against the Vite dev server (hot reload)
```

In dev mode the Vite server proxies `/api` to a local backend
(`CC_API_TARGET`, default `127.0.0.1:8770`), so dev does not require Tailscale.

## macOS builds

A macOS `.app`/`.dmg` **cannot be built or codesigned from Linux**, so the Mac
bundle is built **on the Mac** and delivered to monarch over the tailnet:

- **macOS** — on the Mac: clone the repo, install the prerequisites above, set
  `desktop/.env`, then `bash scripts/ship-desktop-release.sh <version>` from the
  repo root. That builds the universal bundle and rsyncs it to monarch over the
  tailnet. For personal use the app is unsigned to *Gatekeeper* — right-click →
  *Open* the first time.
- **Linux + signing + publish** — on monarch:
  `bash scripts/sign-and-publish.sh <version>`.

**The updater private key never leaves monarch.** The Mac ships *unsigned*
bundles; monarch signs them against key `F22552CEA2BC1655` — the key already
committed as `pubkey` in `tauri.conf.json` and therefore already trusted by every
installed app. One key, one box, no secret on a second machine.

> **GitHub Actions was retired 2026-07-27.** It existed only to rent a macOS
> runner, and cost 4.4 GB of artifact storage against a 500 MB quota — 8.8× over
> — because every run uploaded ~210 MB of bundles whose destination was this box
> anyway. The signing key lives at `~/.config/command-center/tauri-updater.key`
> and always did, so nothing was lost by dropping it.

## Auto-update (G7)

The bundled app self-updates from the **tailnet backend** — no reinstall. It is
**silent** and applies on the **next launch**, so the interactive intro is never
disturbed: on launch the app plays the intro as always and, in the background
(gated on the Tauri runtime, deferred off the intro's first paint), checks the
feed and downloads+installs any newer signed build **without relaunching**. The
new version is live the next time you open the app; a subtle "Updated to vX ·
active next launch" note shows in the dashboard chrome after the intro.

**Feed:** the backend serves `GET /desktop/latest.json` + `/desktop/bundles/*`
from `CC_DESKTOP_UPDATE_DIR` (default `~/.local/state/command-center/desktop-updates/`),
at the same tailnet origin the app already uses (`CC_DESKTOP_API_BASE`). It is
**dormant** (404) until something is published — the tailnet is the trust
boundary, and the updater additionally verifies every bundle's signature against
the committed public key.

**Cut a release (operator-triggered):**

```bash
# 1) bump version in desktop/src-tauri/tauri.conf.json, commit
# 2) ON THE MAC — build the universal bundle, ship it to monarch over tailnet:
bash scripts/ship-desktop-release.sh <new-version>
# 3) ON MONARCH — build Linux, sign everything, publish, verify the live feed:
bash scripts/sign-and-publish.sh <new-version>
```

`publish-desktop-update` harvests the signed bundles out of a **local** build
tree, drops them in the serve dir, and writes `latest.json`. It refuses to
publish a feed the app would reject (key-id mismatch, raw space in a URL, a
missing darwin arch). **Rollback** = re-publish an older signed build (it
supersedes the feed) — note this needs that build's `.sig`, which now means
re-signing locally rather than re-downloading a CI run.

**One-time setup:** generate an updater keypair (`tauri signer generate`); the
**public** key is committed in `tauri.conf.json`; add the **private** key +
password as the `TAURI_SIGNING_PRIVATE_KEY` / `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
repo secrets. Without them the build still succeeds — it just emits no `.sig`, and
the publish bridge skips that platform (a clean no-op). The tailnet host is never
committed: the real updater endpoint is injected at build (like the CSP and
`VITE_API_BASE`), overriding the placeholder in `tauri.conf.json`.

## How the same frontend serves two faces

`../web` builds two ways from one source — both from `index.html`, the whole app
(intro + console + router):
- `npm run build` → `web/dist`, **with** the PWA service worker, served
  same-origin by FastAPI (browser + phone PWA).
- `npm run build:tauri` → `web/dist-tauri`, the same app **without** the service
  worker (the webview loads bundled local assets, so there is nothing to install
  or precache). This is what the native bundle carries. `apiBase.js` rewrites
  `/api` to the tailnet backend at runtime by inspecting the origin, so the one
  source serves both faces.
