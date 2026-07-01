#!/usr/bin/env bash
# deploy.sh — install Loki v0.1 on monarch
# Run from the directory containing this file (~/projects/loki/)
#
# What it does:
#   1. Verifies prerequisites (venv, nvidia-smi)
#   2. Installs pydantic into the inference venv (already present via litellm)
#   3. Creates state/log directories
#   4. Installs loki-q symlink into ~/bin/
#   5. Adds a 'loki' window to the control tmux session (v19 Path B)
#   6. Verifies the daemon starts and produces a state file

set -euo pipefail

LOKI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-$HOME/venv/inference}"
STATE_DIR="$HOME/.local/state/loki"
BIN_DIR="$HOME/bin"

# ─── Topology (v19 Path B) ──────────────────────────────────────────────────
# Loki runs in the long-lived `control` tmux session alongside T1/LiteLLM/
# validation-gate/lora-dispatcher. Survives `inference-down`. See ~/bin/inference-up
# for the full topology block. The session is created by inference-up; this
# script expects it to exist before the daemon window can be added.
CONTROL_SESSION="${CONTROL_SESSION:-control}"

red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
blue()   { printf '\033[36m%s\033[0m\n' "$*"; }

blue "═══ Loki v0.1 deploy ═══"
blue "Loki dir : $LOKI_DIR"
blue "Venv       : $VENV"

# ─── Prerequisites ────────────────────────────────────────────────────────────
if [ ! -f "$VENV/bin/activate" ]; then
  red "Inference venv not found at $VENV"
  red "Run inference-up first or set VENV=/path/to/your/venv"
  exit 1
fi

if ! command -v nvidia-smi &>/dev/null; then
  red "nvidia-smi not found — VRAM listener will not work"
  exit 1
fi

green "Prerequisites OK"

# ─── Directories ──────────────────────────────────────────────────────────────
mkdir -p "$STATE_DIR" "$BIN_DIR"
green "Directories: $STATE_DIR  $BIN_DIR"

# ─── Python dependencies ──────────────────────────────────────────────────────
# pydantic is almost certainly already installed via litellm, but ensure it.
source "$VENV/bin/activate"
python3 -c "import pydantic; assert int(pydantic.__version__.split('.')[0]) >= 2, 'Need pydantic>=2'" \
  && green "pydantic >= 2 ✓" \
  || {
    yellow "Installing pydantic >= 2…"
    pip install "pydantic>=2.0.0" --quiet
  }

# ─── loki-q symlink ─────────────────────────────────────────────────────────
chmod +x "$LOKI_DIR/bin/loki-q"
ln -sf "$LOKI_DIR/bin/loki-q" "$BIN_DIR/loki-q"
green "Installed: ~/bin/loki-q → $LOKI_DIR/bin/loki-q"

# ─── Verify the package imports cleanly ───────────────────────────────────────
python3 -c "
import sys; sys.path.insert(0, '$LOKI_DIR')
from loki.schema import SystemModel
from loki.state import StateStore
from loki.listeners import VRAMListener, TierHealthListener, ProcessListener, QuotaListener, CronListener
print('Package imports OK')
" || { red "Import check failed — check the output above"; exit 1; }
green "Package imports ✓"

# ─── Start daemon in control tmux session ────────────────────────────────────
if tmux has-session -t "${CONTROL_SESSION}" 2>/dev/null; then
  # Kill any existing loki window first (idempotent re-deploy)
  tmux kill-window -t "${CONTROL_SESSION}":loki 2>/dev/null || true
  sleep 1

  # Supervisor proposal intake stays DEFAULT-OFF: a bare `./deploy.sh` launches
  # the daemon with the var UNSET (byte-for-byte the old behavior). To bring the
  # layer up live, deploy deliberately with it set:
  #     LOKI_SUPERVISOR_PROPOSALS=1 ./deploy.sh
  # The value is passed through from this deploy's environment, never hardcoded,
  # so the deliberate two-step enable contract (supervisor/README.md) is intact.
  tmux new-window -t "${CONTROL_SESSION}" -n loki \
    "source $VENV/bin/activate && \
     source $HOME/.config/inference/api_keys.env && \
     cd $LOKI_DIR && \
     LOKI_STATE_PATH=$STATE_DIR/state.json \
     LOKI_LOG_PATH=$STATE_DIR/daemon.log \
     LOKI_SUPERVISOR_PROPOSALS=${LOKI_SUPERVISOR_PROPOSALS:-} \
     python3 daemon.py 2>&1 | tee $STATE_DIR/daemon.log"

  green "Daemon window created: tmux attach -t ${CONTROL_SESSION} → loki"

  # Wait up to 45s for the state file to appear
  yellow "Waiting for first state write (up to 45s)…"
  for i in $(seq 1 45); do
    if [ -f "$STATE_DIR/state.json" ]; then
      green "State file written after ${i}s ✓"
      break
    fi
    sleep 1
    if [ "$i" -eq 45 ]; then
      red "State file not written in 45s — check: tmux attach -t ${CONTROL_SESSION} → loki window"
      exit 1
    fi
  done

  # Quick sanity check
  source "$VENV/bin/activate"
  python3 "$LOKI_DIR/bin/loki-q" health 2>/dev/null || yellow "(loki-q health returned non-zero — first run may have unknown states)"

else
  yellow "No '${CONTROL_SESSION}' tmux session found."
  yellow "Run ~/bin/inference-up first (it creates the control session), then re-run deploy.sh."
  yellow "Or start the daemon manually:"
  echo ""
  echo "  tmux new-session -d -s ${CONTROL_SESSION} -n bootstrap 'sleep infinity'"
  echo "  tmux new-window -t ${CONTROL_SESSION} -n loki"
  echo "  source ~/venv/inference/bin/activate"
  echo "  cd ~/projects/loki && python3 daemon.py"
fi

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
green "═══ Deploy complete ═══"
echo ""
echo "  Query:   loki-q all"
echo "  VRAM:    loki-q vram"
echo "  Health:  loki-q health"
echo "  Events:  loki-q events"
echo "  Daemon:  tmux attach -t ${CONTROL_SESSION} → loki window"
echo "  Logs:    tail -f $STATE_DIR/daemon.log"
