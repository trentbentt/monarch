# Monarch Command Center — Desktop (Tauri)

A native desktop client for the Command Center, for **macOS** and **Linux**. It
renders the operator console in the OS's own webview (WebKit — *not* Chromium, so
no Chrome/Edge engine is involved) and reaches the monarch substrate over
Tailscale. It fires **native OS notifications** on interrupt-class events while
running.

It is a *thin client*: the brain never leaves the monarch box. The FastAPI
backend stays loopback-bound on monarch; this app only exchanges JSON with it
over the tailnet.

```
┌─ Monarch Command Center.app ─┐         monarch box
│  WebKit webview              │  HTTPS  ┌─────────────────────────────┐
│   • bundled local UI assets  │ ──────► │ tailscale serve :8443       │
│   • fetch/SSE → /api ────────┼─(JSON)─►│   → FastAPI 127.0.0.1:8770  │
│   • SSE → native notifs      │  tailnet│   (loopback only)           │
└──────────────────────────────┘  only   └─────────────────────────────┘
```

## Security posture (designed to resist compromise)

| Surface | Hardening |
| --- | --- |
| Webview content | **Bundled & local only.** The privileged webview never navigates to a remote URL; only JSON crosses the wire. Compromising the backend cannot inject code into the privileged context. |
| CSP | `default-src 'self'`; `connect-src` pinned at build time to exactly the one Tailscale backend origin (`object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'self'`). Committed default is `connect-src 'self'`; the build script narrows it. |
| No infra in source | The backend hostname is **never committed** — it is injected at build from a gitignored `desktop/.env`, so the repo carries zero infrastructure details and is safe to push. |
| Navigation | A Rust `on_navigation` guard (`src-tauri/src/lib.rs`) refuses any navigation away from the local asset origin — defence-in-depth behind the CSP. |
| Capabilities | Minimal: `core:default` + `notification:default` only (`src-tauri/capabilities/default.json`). **No** shell, fs, http, dialog, or clipboard access. |
| IPC surface | `withGlobalTauri: false`; no custom commands are exposed to JS. |
| Transport | Tailnet-only HTTPS (`:8443` is *not* internet-funneled). Backend bind stays `127.0.0.1`. |
| Binary | Release profile strips symbols and aborts on panic. |

The backend endpoint lives in exactly one place — `desktop/.env` (gitignored) —
and is injected into both the frontend (`VITE_API_BASE`) and the CSP at build
time by `scripts/build-desktop.sh`. Change it there only.

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
builds the frontend with `VITE_API_BASE`, and bundles with the CSP narrowed to
that endpoint. Outputs land in `src-tauri/target/release/bundle/`:
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

A macOS `.app`/`.dmg` **cannot be built or codesigned from Linux**. Two options:

1. **On a Mac**: clone the repo, install the prerequisites above, set
   `desktop/.env`, then `npm install && npm run build` from `desktop/`
   (add `-- --bundles dmg,app` if you only want those). For personal use the app
   is unsigned — right-click → *Open* the first time to bypass Gatekeeper.
2. **CI**: `.github/workflows/desktop-build.yml` builds a universal macOS bundle
   (+ Linux) on GitHub's hosted runners. Trigger it from the Actions tab or by
   pushing a `desktop-v*` tag. *(This workflow is committed but unverified — it
   has not been run, since pushing this repo is gated on operator review.)*

## How the same frontend serves two faces

`../web` builds two ways from one source:
- `npm run build` → `web/dist`, **relative** `/api` paths, served same-origin by
  FastAPI as the installable PWA. Unchanged by this work.
- `npm run build:tauri` → `web/dist-tauri`, PWA/service-worker omitted;
  `runtime/apiBase.js` rewrites `/api` to the absolute Tailscale backend at
  runtime. This is what the desktop app bundles.
