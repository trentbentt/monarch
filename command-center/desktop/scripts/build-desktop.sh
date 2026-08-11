#!/usr/bin/env bash
#
# Build the native desktop bundle with the backend endpoint injected at build
# time. The endpoint (your Tailscale backend) lives ONLY in a gitignored
# `desktop/.env` — never in committed source — so the repo carries no infra
# details. This builds the WHOLE app (index.html) with VITE_API_BASE and runs
# `tauri build` with the CSP connect-src narrowed to exactly that origin.
#
# The app is fully bundled: it plays the intro locally and reveals the dashboard
# in the same document (no navigation, no download). Only JSON crosses the wire,
# via fetch/SSE to VITE_API_BASE — the webview never renders remote content.
#
# Usage (from anywhere):
#   desktop/scripts/build-desktop.sh                       # default bundles
#   desktop/scripts/build-desktop.sh --bundles deb,appimage
#   desktop/scripts/build-desktop.sh --bundles dmg,app     # on macOS
#
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DESKTOP_DIR"

# Load the local, gitignored endpoint config — but never let it clobber a value
# passed in from the environment. Sourcing .env unconditionally means an explicit
# `CC_DESKTOP_API_BASE=... build-desktop.sh` is silently ignored on any machine
# that happens to have a .env, producing an app pointed somewhere other than
# where you asked. CI (no .env, secret in env) must win too.
PRESET_BASE="${CC_DESKTOP_API_BASE:-}"
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
if [ -n "$PRESET_BASE" ]; then
  CC_DESKTOP_API_BASE="$PRESET_BASE"
fi

: "${CC_DESKTOP_API_BASE:?Set CC_DESKTOP_API_BASE in desktop/.env (see desktop/.env.example), e.g. https://host.your-tailnet.ts.net:8443}"
BASE="${CC_DESKTOP_API_BASE%/}"   # strip any trailing slash

echo "[build-desktop] backend endpoint: $BASE"

# 0) Refuse a cache built somewhere else (M16), BEFORE anything expensive runs.
#    A target/ produced in a container or another checkout makes cargo chase
#    absolute paths off this tree and die naming a missing .toml — a riddle that
#    cost an evening on 2026-07-20. Costs ~0.2s over the whole cache, so it goes
#    first: failing after a 3s frontend build wastes the work and buries the
#    message. `set -e` (above) is what makes this abort rather than merely warn.
"$DESKTOP_DIR/../scripts/check-build-cache.py" \
    "$DESKTOP_DIR/src-tauri/target" "$DESKTOP_DIR/.."

# 1) Frontend bundle (gitignored web/dist-tauri): the WHOLE app from index.html,
#    with the backend origin baked into apiBase.js so /api resolves to the
#    tailnet backend at runtime.
VITE_API_BASE="$BASE" npm --prefix ../web run build:tauri

# 2) Remove any stale remote-console capability from an earlier hybrid build.
#    The bundle model never navigates to a remote origin, so no remote capability
#    is needed — native notifications are covered by the local `default`
#    capability. Tauri v2 auto-discovers every capabilities/*.json, so a leftover
#    file would silently re-grant remote IPC; delete it.
rm -f src-tauri/capabilities/remote.gen.json

# 3) Native bundle. Skip the conf's beforeBuildCommand (frontend already built)
#    and narrow the CSP connect-src to exactly this backend origin (fetch/SSE).
CSP="default-src 'self'; connect-src 'self' ${BASE}; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; script-src 'self'; worker-src 'self' blob:; child-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"

# The updater endpoint carries the tailnet host, so it is injected here at build
# (like the CSP + VITE_API_BASE) — never committed. Overrides the placeholder in
# tauri.conf.json's plugins.updater.endpoints.
CONFIG_OVERRIDE="{\"build\":{\"beforeBuildCommand\":\"\"},\"app\":{\"security\":{\"csp\":\"${CSP}\"}},\"plugins\":{\"updater\":{\"endpoints\":[\"${BASE}/desktop/latest.json\"]}}}"

npx tauri build "$@" -c "$CONFIG_OVERRIDE"
