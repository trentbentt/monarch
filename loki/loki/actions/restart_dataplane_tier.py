"""
Seed action: auto_restart_cpu_dataplane_tier.

The ONLY action registered in P3.1. Restarts a crashed zero-VRAM CPU dataplane
tier (T3 content/batch, T4 Phi-4 grader, T5 small-helper) by shelling out to the
operator's idempotent per-tier launch script (~/bin/t3-up | ~/bin/t4-up |
~/bin/t5-up). Those scripts own the launch flags/ports and recover a single tier
WITHOUT bouncing the whole dataplane — `inference-up` kills the entire `inference`
session, so it is NOT a single-tier restart mechanism (verified against disk
during P3.1 execution).

Scope is the cpu_only & enabled tiers (T3/T4/T5 today — T4 joined 2026-06-16 when
it moved GPU→CPU, §5.4) because they are:
  • zero-VRAM  (CPU-only, CUDA_VISIBLE_DEVICES= ) → no OOM/cascade risk
  • no money   → no quota cascade
  • reversible / self-healing → an idempotent relaunch, confirmed by tier_health

Excluded by design: T1 (Hard Constraint #4 → always Tier 3), T2/T6
(burst/VRAM-significant). Those need their own actions and their own ladders.

Doctrine: master_summary §12.6 (decision flow), §9.5 (authority model).
"""

from __future__ import annotations

import logging
import os
import subprocess

from ..schema import ActionTier, CPU_DATAPLANE_TIERS
from .base import Action

logger = logging.getLogger(__name__)

# Eligibility + launch scripts DERIVED from MONARCH_TIERS (cpu_only & enabled) so
# this action and rules.py share one tier set — see schema.CPU_DATAPLANE_TIERS.
# Today: {"t3","t4","t5"} → ~/bin/t3-up | ~/bin/t4-up | ~/bin/t5-up.
_ALLOWED_TIERS = set(CPU_DATAPLANE_TIERS)
_TIER_SCRIPT = {tid: os.path.expanduser(f"~/bin/{tid}-up") for tid in CPU_DATAPLANE_TIERS}
# The launch scripts wait up to HEALTH_TIMEOUT (180s for T3, 120s for T4/T5) for
# /health; give the subprocess a margin beyond the longest of those.
_RESTART_TIMEOUT_SEC = 240


class RestartCpuDataplaneTier(Action):
    action_id   = "auto_restart_cpu_dataplane_tier"
    description = "Restart a crashed zero-VRAM CPU dataplane tier (T3/T4/T5) via idempotent per-tier launch script"
    default_tier = ActionTier.TIER_3     # strict cold-start (§9.5.2)
    target_tier  = ActionTier.TIER_2     # caps at autonomous-with-log; never TIER_1 (would be user-invisible)
    reversible   = True
    costs_money  = False
    vram_mb      = 0

    def matches(self, params: dict) -> bool:
        return params.get("tier") in _ALLOWED_TIERS

    def execute(self, params: dict) -> str:
        """Shell out to the tier's idempotent launch script. Returns "ok" when
        the script exits 0 (tier responded to /health), else "failed".
        tier_health.py independently confirms recovery on its next poll, so "ok"
        means "relaunched cleanly", not "verified by an external observer"."""
        tier = params.get("tier")
        if tier not in _ALLOWED_TIERS:
            logger.error("[action:restart] refusing out-of-scope tier %r", tier)
            return "failed"

        script = _TIER_SCRIPT[tier]
        if not os.path.isfile(script) or not os.access(script, os.X_OK):
            logger.error("[action:restart] launch script missing/not-executable: %s", script)
            return "failed"

        try:
            logger.info("[action:restart] %s → %s", tier, script)
            proc = subprocess.run(
                [script],
                capture_output=True,
                text=True,
                timeout=_RESTART_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            logger.error("[action:restart] %s timed out after %ds", tier, _RESTART_TIMEOUT_SEC)
            return "failed"
        except Exception as exc:  # never raise — the gate records the outcome
            logger.error("[action:restart] %s raised %s: %s", tier, type(exc).__name__, exc)
            return "failed"

        if proc.returncode == 0:
            logger.info("[action:restart] %s restarted ok", tier)
            return "ok"

        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        logger.error("[action:restart] %s failed (rc=%d): %s", tier, proc.returncode, " | ".join(tail))
        return "failed"
