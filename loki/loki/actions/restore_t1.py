"""
Action: restore_t1_reasoning — reverse of offload_t1_reasoning (§10.3).

Returns T1 to full GPU residency (-ngl 40) at overnight-window end (or when the
operator demands it). Fires as a **Tier-2** action (autonomous-with-log):
restoring reasoning capacity is always safe and reversible, so it does not need
a veto window — it just logs. Shells to ~/bin/t1-restore (idempotent: no-op if
T1 is already at full config).

Doctrine: master_summary §10.3 (Substrate Pressure Cascade), §9.5.2 (Tier 2).
"""

from __future__ import annotations

import logging
import os
import subprocess

from ..schema import ActionTier
from .base import Action

logger = logging.getLogger(__name__)

_SCRIPT = os.path.expanduser("~/bin/t1-restore")
_RESTORE_TIMEOUT_SEC = 240


class RestoreT1Reasoning(Action):
    action_id   = "restore_t1_reasoning"
    description = "Restore T1 reasoning to full GPU residency (-ngl 40) after an offload (§10.3)"
    default_tier = ActionTier.TIER_2     # autonomous-with-log — restoring capacity is always safe
    target_tier  = ActionTier.TIER_2
    reversible   = True
    costs_money  = False
    vram_mb      = 0                     # restores T1's own VRAM; bounded by the freed headroom

    def matches(self, params: dict) -> bool:
        return True

    def execute(self, params: dict) -> str:
        if not (os.path.isfile(_SCRIPT) and os.access(_SCRIPT, os.X_OK)):
            logger.error("[action:restore_t1] launch script missing/not-executable: %s", _SCRIPT)
            return "failed"
        try:
            logger.info("[action:restore_t1] → %s", _SCRIPT)
            proc = subprocess.run(
                [_SCRIPT], capture_output=True, text=True, timeout=_RESTORE_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            logger.error("[action:restore_t1] timed out after %ds", _RESTORE_TIMEOUT_SEC)
            return "failed"
        except Exception as exc:
            logger.error("[action:restore_t1] raised %s: %s", type(exc).__name__, exc)
            return "failed"

        if proc.returncode == 0:
            logger.info("[action:restore_t1] T1 restored ok")
            return "ok"

        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        logger.error("[action:restore_t1] failed (rc=%d): %s", proc.returncode, " | ".join(tail))
        return "failed"
