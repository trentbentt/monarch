#!/usr/bin/env bash
#
# Build the native desktop bundle with the backend endpoint injected at build
# time. The endpoint (your Tailscale backend) lives ONLY in a gitignored
# `desktop/.env` — never in committed source — so the repo carries no infra
# details. This builds the frontend with VITE_API_BASE and runs `tauri build`
# with the CSP connect-src narrowed to exactly that origin.
#
# Usage (from anywhere):
#   desktop/scripts/build-desktop.sh                       # default bundles
#   desktop/scripts/build-desktop.sh --bundles deb,appimage
#   desktop/scripts/build-desktop.sh --bundles dmg,app     # on macOS
#
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DESKTOP_DIR"

# Load the local, gitignored endpoint config.
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

: "${CC_DESKTOP_API_BASE:?Set CC_DESKTOP_API_BASE in desktop/.env (see desktop/.env.example), e.g. https://host.your-tailnet.ts.net:8443}"
BASE="${CC_DESKTOP_API_BASE%/}"   # strip any trailing slash

echo "[build-desktop] backend endpoint: $BASE"

# 1) Frontend bundle (gitignored web/dist-tauri) with the API base baked in.
VITE_API_BASE="$BASE" npm --prefix ../web run build:tauri

# 2) Native bundle. Skip the conf's beforeBuildCommand (frontend already built)
#    and narrow the CSP connect-src to exactly this backend origin.
CSP="default-src 'self'; connect-src 'self' ${BASE}; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; script-src 'self'; worker-src 'self' blob:; child-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"

CONFIG_OVERRIDE="{\"build\":{\"beforeBuildCommand\":\"\"},\"app\":{\"security\":{\"csp\":\"${CSP}\"}}}"

npx tauri build "$@" -c "$CONFIG_OVERRIDE"
