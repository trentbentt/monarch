"""
Action: offload_t1_reasoning — Substrate Pressure Cascade T1 self-offload (§10.3).

Under sustained VRAM pressure inside the overnight weekday window, Loki
offloads a portion of T1's layers GPU → CPU/DDR5 (reduced -ngl) to free VRAM for
a T2/T6 burst. Fires as a **non-blocking Tier-3** action: the gate surfaces a
120-second veto window ("offloading T1 to RAM in 120s unless you veto") and
default-proceeds at timeout (§9.5.1 / §10.3). Hard Constraint #1 is preserved —
the Loki daemon never stops; only the T1 llama-server window is relaunched at
a lower -ngl. Reverse: restore_t1_reasoning.

Shells to ~/bin/t1-offload, which owns the launch flags + `control`-session
topology — same delegation pattern as restart_dataplane_tier → ~/bin/t{3,4,5}-up.

Doctrine: master_summary §10.3 (Substrate Pressure Cascade), §9.5.1 (non-blocking
Tier 3), §9.5.3 (overnight window gating — applied by the rule, not here).
"""

from __future__ import annotations

import logging
import os
import subprocess

from ..schema import ActionTier
from .base import Action

logger = logging.getLogger(__name__)

_SCRIPT = os.path.expanduser("~/bin/t1-offload")
# ~/bin/t1-offload waits up to its own HEALTH_TIMEOUT (180s) for the relaunched
# T1 to bind /health; give the subprocess a margin beyond that.
_OFFLOAD_TIMEOUT_SEC = 240


class OffloadT1Reasoning(Action):
    action_id   = "offload_t1_reasoning"
    description = "Offload a portion of T1 reasoning GPU→CPU/DDR5 (reduced -ngl) to free VRAM for a burst (§10.3)"
    default_tier = ActionTier.TIER_3     # surface-and-ask (non-blocking, see veto window)
    target_tier  = ActionTier.TIER_3     # never auto-promotes — a disruptive move always wants the veto
    reversible   = True                  # ~/bin/t1-restore
    costs_money  = False
    vram_mb      = 0                     # FREES VRAM (does not consume)

    # §9.5.1 / §10.3: non-blocking Tier 3 — the gate surfaces a PendingAsk with a
    # deadline this many seconds out, then default-proceeds unless the operator
    # vetoes. None on an action = classic blocking Tier 3 (wait for approval).
    nonblocking_veto_sec = 120

    def matches(self, params: dict) -> bool:
        return True

    def execute(self, params: dict) -> str:
        """Shell out to ~/bin/t1-offload (idempotent). "ok" = relaunched cleanly
        (vram.py confirms the freed VRAM on its next poll), else "failed"."""
        if not (os.path.isfile(_SCRIPT) and os.access(_SCRIPT, os.X_OK)):
            logger.error("[action:offload_t1] launch script missing/not-executable: %s", _SCRIPT)
            return "failed"
        try:
            logger.info("[action:offload_t1] → %s", _SCRIPT)
            proc = subprocess.run(
                [_SCRIPT], capture_output=True, text=True, timeout=_OFFLOAD_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            logger.error("[action:offload_t1] timed out after %ds", _OFFLOAD_TIMEOUT_SEC)
            return "failed"
        except Exception as exc:  # never raise — the gate records the outcome
            logger.error("[action:offload_t1] raised %s: %s", type(exc).__name__, exc)
            return "failed"

        if proc.returncode == 0:
            logger.info("[action:offload_t1] T1 offloaded ok")
            return "ok"

        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        logger.error("[action:offload_t1] failed (rc=%d): %s", proc.returncode, " | ".join(tail))
        return "failed"
