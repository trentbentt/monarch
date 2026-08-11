"""
Action contract — the executor interface the AuthorityGate classifies and runs.

An Action is a single, named autonomous behavior Loki may perform. The gate
reads the class-level metadata (default_tier, target_tier, reversible,
costs_money, vram_mb, action_class) to classify and bound each action; it
never infers risk. `execute()` performs the side effect; `verify()`
independently confirms it; the ledger records "ok" only when both pass.

Doctrine: master_summary §12.6 (decision-engine flow) + §9.5 (three-tier
authority model). Adding an action is a deliberate decision: the seed
(restart_dataplane_tier) proves the N=12 ladder; the T1 self-offload pair
(offload_t1_reasoning / restore_t1_reasoning, §10.3) was added 2026-06-16;
the autonomy-spine Phase A contract (action_class ceiling, mandatory verify,
enabled kill switch) landed 2026-07-13 per DESIGN_autonomy-spine v1.1.
"""

from __future__ import annotations

import urllib.request
from abc import ABC, abstractmethod
from typing import Optional

from ..schema import ActionTier

# Autonomy-spine action classes (DESIGN_autonomy-spine_2026-07-12 v1.1). The
# class is the operator's risk ceiling IN CODE: only service-lifecycle actions
# may ever target an autonomous tier (TIER_2/TIER_1); every other class is
# surface-and-ask forever, enforced by the loader assertion in
# actions/__init__.py — a mis-declared action refuses to LOAD.
ACTION_CLASSES = frozenset({
    "service-lifecycle",   # start/stop/restart of stack services — the ONLY auto-eligible class
    "state-write",
    "config-change",
    "git-commit",
    "cloud-spend",
})


def _http_ok(url: str, timeout: float = 5.0) -> bool:
    """Tiny stdlib health probe shared by verify() implementations. False on
    any error — verify must never raise."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


class Action(ABC):
    """Subclass and set the metadata + implement matches()/execute()/verify().

    Metadata is class-level and read by AuthorityGate at classify time:
      action_id     — stable behavior id; key into ACTIONS and the ledger
      description    — human-readable, surfaced in loki-q
      default_tier   — cold-start authority tier (TIER_3 by doctrine §9.5.2)
      target_tier    — promotion cap; the ladder never climbs past this
      reversible     — does this action have a clean undo / is it self-healing
      costs_money    — gates anything touching paid cloud quotas (out of scope)
      vram_mb        — VRAM footprint; >0 = the action OCCUPIES VRAM when it runs
      nonblocking_veto_sec — §9.5.1: when set, a Tier-3 dispatch surfaces a veto
                     window N seconds out and DEFAULT-PROCEEDS at timeout unless
                     the operator vetoes. None (default) = classic blocking Tier 3
                     (the ask waits for explicit approval). Only consulted at
                     Tier 3; ignored at Tier 1/2.
      action_class   — ACTION_CLASSES member; only "service-lifecycle" may
                     target TIER_2/TIER_1 (loader-asserted, autonomy spine A)
      enabled        — per-action kill switch; False = proposals dropped at
                     dispatch, no ask, no execution
    """

    action_id: str
    description: str
    default_tier: ActionTier
    target_tier: ActionTier
    reversible: bool
    costs_money: bool
    vram_mb: int
    nonblocking_veto_sec: Optional[int] = None
    action_class: str
    enabled: bool = True

    @abstractmethod
    def matches(self, params: dict) -> bool:
        """Guard: are these params valid/in-scope for this action?"""
        ...

    @abstractmethod
    def execute(self, params: dict) -> str:
        """Perform the side effect. Return outcome: "ok" | "failed".

        Must not raise — catch internally and return "failed". Execute-time
        freshness guards (re-probing the condition the rule saw in a lagging
        snapshot) live HERE, inline, per the evict_burst precedent.
        """
        ...

    @abstractmethod
    def verify(self, params: dict) -> str:
        """Independent post-execute success probe. Return "ok" | "failed".
        Must not raise. NO VERIFIER, NO AUTONOMY: the registry refuses to load
        an action without one, and the gate records outcome "ok" only when
        execute() AND verify() both return "ok"."""
        ...

    def rollback(self, params: dict) -> str:
        """Best-effort undo after a verify failure. Return "ok" | "failed" |
        "unsupported". Must not raise. Default: no rollback available."""
        return "unsupported"

    def plan(self, params: dict) -> str:
        """Prepared-action text for the operator's ask surface (CC card /
        push). Override with the concrete command + verify + rollback story."""
        return f"{self.description} (params={params})"
