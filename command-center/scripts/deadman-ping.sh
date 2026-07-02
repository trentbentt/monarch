#!/usr/bin/env bash
# Dead-man's-switch heartbeat — Layer B of the "is monarch alive?" story.
#
# WHY THIS EXISTS OFF-BOX LOGIC RUNS ON-BOX: a dead monarch cannot send its own
# alert (no power, no push). So instead monarch phones OUT to an external monitor
# on a schedule; when the check-ins STOP (power loss / crash / network down), the
# external monitor — which is not on monarch — is the thing that alerts you.
#
# This is outbound-only (a single HTTPS GET/POST). It exposes NOTHING inbound and
# needs no Funnel, matching the webhook/outbound-only doctrine.
#
# Pairs with the in-app Layer A (web/src/runtime/reachability.js), which only
# covers the window while the app is open. This covers the app-closed / overnight
# outage that Layer A structurally cannot.
#
# ACTIVATION (operator, ~2 min):
#   1. Create a check at a dead-man's-switch service you control, e.g.
#      https://healthchecks.io (free tier). Set Period = 5 min, Grace = 5 min,
#      and add your alert channel (push to the Healthchecks mobile app / email /
#      SMS / ntfy / Pushover / etc.). Copy its ping URL.
#   2. Put the URL where this script reads it (first match wins):
#        - env CC_DEADMAN_URL, or
#        - a file at ~/.config/inference/deadman.url  (chmod 600)
#   3. Install the timer:  see deploy/deadman.timer / deploy/deadman.service
#      cp deploy/deadman.{service,timer} ~/.config/systemd/user/
#      systemctl --user daemon-reload
#      systemctl --user enable --now deadman.timer
#   4. Confirm: `systemctl --user list-timers | grep deadman` and that the check
#      goes green in the service dashboard.
#
# Until a URL is provided this script is a deliberate no-op (exit 0), so it is
# safe to install the timer first and wire the URL later.

set -euo pipefail

URL="${CC_DEADMAN_URL:-}"
URL_FILE="${CC_DEADMAN_URL_FILE:-$HOME/.config/inference/deadman.url}"
if [[ -z "$URL" && -r "$URL_FILE" ]]; then
  URL="$(tr -d ' \t\r\n' < "$URL_FILE")"
fi

if [[ -z "$URL" ]]; then
  echo "deadman-ping: no CC_DEADMAN_URL / $URL_FILE set — skipping (no-op)." >&2
  exit 0
fi

# OPTIONAL local liveness gate: only check in if the Command Center backend is
# actually answering, so a wedged box (kernel alive, services dead) still trips
# the switch. Health endpoint is loopback; adjust the port if you customized it.
HEALTH_URL="${CC_HEALTH_URL:-http://127.0.0.1:8780/api/health}"
if ! curl -fsS --max-time 5 -o /dev/null "$HEALTH_URL" 2>/dev/null; then
  echo "deadman-ping: local health check ($HEALTH_URL) failed — NOT checking in so the switch trips." >&2
  # Signal failure to healthchecks.io-style services via the /fail suffix if used.
  curl -fsS --max-time 10 -o /dev/null "${URL%/}/fail" 2>/dev/null || true
  exit 0
fi

# BACKUP FRESHNESS GATE (2026-07-02, system-review L2-#7): the Jul-1 outage
# silently skipped a full backup day — user cron has no anacron-style catch-up
# and nothing watched backup RECENCY (pg-backup checks integrity, not age).
# Piggyback the alert channel that already exists: if any backup family's
# newest artifact is older than 48h, signal /fail with the reason instead of
# checking in, so the external monitor alerts. Same pattern as the health gate.
# Override the roots for testing via CC_BACKUP_ROOTS (space-separated dirs).
BACKUP_MAX_AGE_HOURS="${CC_BACKUP_MAX_AGE_HOURS:-48}"
BACKUP_ROOTS="${CC_BACKUP_ROOTS:-$HOME/backups/hermes $HOME/backups/evercore-mongo $HOME/backups/postgres $HOME/backups/l1-redis $HOME/backups/config}"
stale=()
for dir in $BACKUP_ROOTS; do
  # newest regular file anywhere under the family dir, in whole hours
  newest=$(find "$dir" -type f -printf '%T@\n' 2>/dev/null | sort -rn | head -1)
  if [[ -z "$newest" ]]; then
    stale+=("$(basename "$dir"):empty")
    continue
  fi
  age_h=$(( ($(date +%s) - ${newest%.*}) / 3600 ))
  if (( age_h > BACKUP_MAX_AGE_HOURS )); then
    stale+=("$(basename "$dir"):${age_h}h")
  fi
done
if (( ${#stale[@]} > 0 )); then
  reason="backup freshness gate: ${stale[*]} exceed ${BACKUP_MAX_AGE_HOURS}h"
  echo "deadman-ping: $reason — NOT checking in so the switch trips." >&2
  curl -fsS --max-time 10 -o /dev/null --data "$reason" "${URL%/}/fail" 2>/dev/null || true
  exit 0
fi

# Heartbeat: a healthy check-in. --retry rides out a brief blip without tripping.
curl -fsS --max-time 10 --retry 2 -o /dev/null "$URL"
echo "deadman-ping: checked in OK."
