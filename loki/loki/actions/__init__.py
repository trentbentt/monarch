"""
Action registry. ACTIONS maps action_id → Action instance.

Seed action: restart_dataplane_tier (the N=12 ladder is proven on it).

T1 self-offload pair added 2026-06-16 (deliberate expansion per operator goal):
the §10.3 Substrate Pressure Cascade — offload_t1_reasoning (non-blocking Tier-3
with a 120s veto window) frees VRAM for a burst; restore_t1_reasoning (Tier-2)
reverses it at overnight-window end. These cold-start at their default tiers and
run the same authority ladder.

evict_idle_burst_tier added 2026-06-28 (§10.3 cascade rung 1): under VRAM
pressure, evict an IDLE burst tier (T2/T6) GPU→down to reclaim headroom BEFORE
the last-resort T1 self-offload. Idle-guarded by the /slots probe; cold-starts
Tier-3 (operator-gated) and caps at Tier-2 (autonomous-with-log).
"""

from .base import Action
from .restart_dataplane_tier import RestartCpuDataplaneTier
from .offload_t1 import OffloadT1Reasoning
from .restore_t1 import RestoreT1Reasoning
from .evict_burst import EvictIdleBurstTier

ACTIONS: dict[str, Action] = {
    a.action_id: a for a in (
        RestartCpuDataplaneTier(),
        OffloadT1Reasoning(),
        RestoreT1Reasoning(),
        EvictIdleBurstTier(),
    )
}

__all__ = ["Action", "ACTIONS"]
