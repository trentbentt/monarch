"""
Action: evict_idle_burst_tier — §10.3 Substrate Pressure Cascade, rung 1.

Under VRAM pressure the cascade reclaims headroom from the *highest-priority*
rungs before the last-resort T1 self-offload: evict burst tiers (T2 ~6.8 GB,
later T6) GPU→down. This action shells out to the operator's idempotent
bring-down script (~/bin/t2-down | ~/bin/t6-down), which writes the clean-idle
marker so tier_health reports IDLE (not a crash) afterward.

Idle-guard lives in the RULE (rules.py:evict_idle_burst_under_pressure): the
proposal only fires when the burst has zero in-flight requests (the /slots probe
in tier_health populates runtime.active_requests). The action itself just
performs the eviction it was handed — it never kills a tier the rule didn't
clear as idle, and an actively-serving burst is never proposed.

Authority: cold-starts Tier 3 but NON-BLOCKING (nonblocking_veto_sec=120,
§9.5.1, mirrors offload_t1_reasoning) — under pressure it surfaces a 120s veto
window and DEFAULT-PROCEEDS, so it prevents collapse autonomously from day one
("prevent while away") while the operator can still veto ("react when present").
Caps at Tier 2 (autonomous-with-log, §10.3 "eviction = standard Tier-2 actions")
once the N=12 ladder is climbed, at which point the veto window drops.

Doctrine: master_summary §10.3 (cascade), §9.5 (authority), §12.6 (decision flow).
"""

from __future__ import annotations

import logging
import os
import subprocess

from ..schema import ActionTier, BURST_TIERS, MONARCH_TIERS
from ..listeners.tier_health import _slots_active_count
from .base import Action

logger = logging.getLogger(__name__)

# Eligibility + bring-down scripts DERIVED from MONARCH_TIERS (burst_only &
# enabled) so this action and rules.py share one tier set — see schema.BURST_TIERS.
# Today: {"t2"} → ~/bin/t2-down. T6 joins automatically once it flips enabled.
_ALLOWED_TIERS = set(BURST_TIERS)
_TIER_SCRIPT = {tid: os.path.expanduser(f"~/bin/{tid}-down") for tid in BURST_TIERS}
# t2-down/t6-down are SIGTERM-then-SIGKILL teardowns + marker write — fast.
_EVICT_TIMEOUT_SEC = 30


class EvictIdleBurstTier(Action):
    action_id   = "evict_idle_burst_tier"
    description = "Evict an idle burst tier (T2/T6) GPU→down to reclaim VRAM under §10.3 pressure (cascade rung before T1 offload)"
    default_tier = ActionTier.TIER_3     # strict cold-start (§9.5.2)
    target_tier  = ActionTier.TIER_2     # §10.3: eviction is a standard autonomous-with-log action
    reversible   = True                  # ~/bin/t{n}-up brings the burst back
    costs_money  = False
    vram_mb      = 0                      # frees VRAM; does not consume it
    # Non-blocking from cold start (§9.5.1, mirrors offload_t1_reasoning): under
    # pressure the eviction surfaces a 120s veto window and DEFAULT-PROCEEDS —
    # autonomous "prevent while away" — yet the operator can veto ("react when
    # present"). Safe to auto-proceed because evicting an idle burst is reversible
    # AND execute() re-probes /slots fresh, refusing to evict a now-busy burst.
    nonblocking_veto_sec = 120

    def matches(self, params: dict) -> bool:
        return params.get("tier") in _ALLOWED_TIERS

    def execute(self, params: dict) -> str:
        """Shell out to the burst tier's idempotent bring-down script. Returns
        "ok" on exit 0, else "failed". tier_health confirms the tier left GPU
        (IDLE) on its next poll, so "ok" means "brought down cleanly", not
        "verified by an external observer". Never raises — the gate records
        whatever is returned."""
        tier = params.get("tier")
        if tier not in _ALLOWED_TIERS:
            logger.error("[action:evict] refusing out-of-scope tier %r", tier)
            return "failed"

        script = _TIER_SCRIPT[tier]
        if not os.path.isfile(script) or not os.access(script, os.X_OK):
            logger.error("[action:evict] bring-down script missing/not-executable: %s", script)
            return "failed"

        # Execute-time freshness guard: the rule idle-gated off the snapshot,
        # which lags the /slots probe by up to one tier_health sweep (~15s). Since
        # this action is non-blocking (default-proceeds after the veto window), a
        # burst that started serving inside that window could otherwise be killed.
        # Re-probe /slots NOW and abort unless provably idle — busy (>0) or
        # unknown (None) → refuse, never evict live work.
        active = _slots_active_count(MONARCH_TIERS[tier].port)
        if active != 0:
            logger.warning("[action:evict] %s aborted: burst not provably idle at dispatch "
                           "(active_requests=%s) — refusing to evict live work", tier, active)
            return "failed"

        try:
            logger.info("[action:evict] %s → %s", tier, script)
            proc = subprocess.run(
                [script],
                capture_output=True,
                text=True,
                timeout=_EVICT_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            logger.error("[action:evict] %s timed out after %ds", tier, _EVICT_TIMEOUT_SEC)
            return "failed"
        except Exception as exc:  # never raise — the gate records the outcome
            logger.error("[action:evict] %s raised %s: %s", tier, type(exc).__name__, exc)
            return "failed"

        if proc.returncode == 0:
            logger.info("[action:evict] %s evicted ok", tier)
            return "ok"

        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        logger.error("[action:evict] %s failed (rc=%d): %s", tier, proc.returncode, " | ".join(tail))
        return "failed"
