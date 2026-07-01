#!/usr/bin/env bash
# Launch the tailnet-only hey_loki real-mic recorder.
#   - mints a per-session token (never logged on its own line)
#   - serves FastAPI on 127.0.0.1:8791 (local only)
#   - exposes it over tailscale serve at tailnet HTTPS :8444 (NOT funnel)
#   - on exit removes ONLY the :8444 mapping (leaves 443/8443 intact)
#
# Usage:
#   serve.sh           # eval profile  -> realmic_eval/  (held-out test set)
#   serve.sh train     # train profile -> realmic_train/ (real positives to anchor training)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY=~/venv/voice-train/bin/python3
PORT_LOCAL=8791
PORT_TS=8444

PROFILE="${1:-eval}"
case "$PROFILE" in
  eval)  OUT_SUBDIR="realmic_eval" ;;
  train) OUT_SUBDIR="realmic_train" ;;
  *) echo "ERROR: unknown profile '$PROFILE' (use 'eval' or 'train')"; exit 1 ;;
esac

command -v ffmpeg >/dev/null || { echo "ERROR: ffmpeg required (sudo apt-get install -y ffmpeg)"; exit 1; }

export REALMIC_TOKEN="$($PY -c 'import secrets; print(secrets.token_urlsafe(16))')"
export REALMIC_PROFILE="$PROFILE"
export REALMIC_OUT="$HERE/../$OUT_SUBDIR"
mkdir -p "$REALMIC_OUT"
NODE="$(tailscale status --json | $PY -c 'import sys,json; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"

cleanup() {
  tailscale serve --https=$PORT_TS off >/dev/null 2>&1 || true
  [ -n "${UV:-}" ] && kill "$UV" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

$PY -m uvicorn server:app --app-dir "$HERE" --host 127.0.0.1 --port $PORT_LOCAL &
UV=$!
sleep 2
tailscale serve --bg --https=$PORT_TS "$PORT_LOCAL"

echo "================================================================"
echo " Recorder live (tailnet only) — profile: $PROFILE -> $OUT_SUBDIR/"
echo " Open on your Mac/iPhone:"
echo "   https://$NODE:$PORT_TS/?token=$REALMIC_TOKEN"
echo " Ctrl-C when done (removes the :$PORT_TS mapping, keeps 443/8443)."
echo "================================================================"
wait $UV
