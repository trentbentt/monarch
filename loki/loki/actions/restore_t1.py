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

from ..schema import ActionTier, MONARCH_TIERS
from ..listeners.process import _t1_offload_state
from .base import Action, _http_ok

logger = logging.getLogger(__name__)

_SCRIPT = os.path.expanduser("~/bin/t1-restore")
_RESTORE_TIMEOUT_SEC = 240

# Reverse script, run by rollback(): re-offloading returns T1 to the reduced-ngl
# state it was in before this action. Same script offload_t1_reasoning shells to.
_REVERSE_SCRIPT = os.path.expanduser("~/bin/t1-offload")
_REVERSE_TIMEOUT_SEC = 240


class RestoreT1Reasoning(Action):
    action_id   = "restore_t1_reasoning"
    action_class = "service-lifecycle"
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

    def verify(self, params: dict) -> str:
        """T1 must answer /health AND be back at full GPU residency.

        This docstring used to promise "at full GPU residency" while the code
        checked only the port — and the port answers identically whether T1 is
        offloaded or not, so a no-op restore verified as success (agentbench #5,
        2026-07-16). ~/bin/t1-restore clears the offload marker on success, so
        marker-absent is the residency proof; it is the same source of truth
        process.py reads for tier.runtime.offloaded.
        """
        port = MONARCH_TIERS["t1"].port
        if not _http_ok(f"http://127.0.0.1:{port}/health", timeout=10.0):
            logger.error("[action:restore_t1] verify: T1 not answering /health")
            return "failed"
        offloaded, ngl = _t1_offload_state()
        if offloaded:
            logger.error("[action:restore_t1] verify: T1 answers but is STILL "
                         "offloaded (ngl=%s) — the restore did not take effect", ngl)
            return "failed"
        logger.info("[action:restore_t1] verify: T1 at full GPU residency")
        return "ok"

    def rollback(self, params: dict) -> str:
        """Undo by re-offloading — return T1 to the reduced-ngl state it was in
        before this action.

        The gate calls rollback() only when execute() said "ok" but verify()
        said "failed": T1 is off its port or stuck mid-restore. A degraded but
        LIVE reasoning brain beats a dead one, and no rule autonomously recovers
        a downed T1. Previously returned "unsupported" while the class declared
        reversible=True (agentbench #5, 2026-07-16).
        """
        if not (os.path.isfile(_REVERSE_SCRIPT) and os.access(_REVERSE_SCRIPT, os.X_OK)):
            logger.error("[action:restore_t1] rollback: reverse script "
                         "missing/not-executable: %s", _REVERSE_SCRIPT)
            return "failed"
        try:
            logger.warning("[action:restore_t1] rollback → %s", _REVERSE_SCRIPT)
            proc = subprocess.run(
                [_REVERSE_SCRIPT], capture_output=True, text=True,
                timeout=_REVERSE_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            logger.error("[action:restore_t1] rollback timed out after %ds",
                         _REVERSE_TIMEOUT_SEC)
            return "failed"
        except Exception as exc:  # never raise — the gate records the outcome
            logger.error("[action:restore_t1] rollback raised %s: %s",
                         type(exc).__name__, exc)
            return "failed"
        if proc.returncode == 0:
            logger.info("[action:restore_t1] rollback ok — T1 back on reduced -ngl")
            return "ok"
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        logger.error("[action:restore_t1] rollback FAILED (rc=%d): %s — T1 may "
                     "be down; operator attention needed",
                     proc.returncode, " | ".join(tail))
        return "failed"
