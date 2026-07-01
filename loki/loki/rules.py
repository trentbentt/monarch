"""
Rule registry — pure functions over a SystemModel snapshot.

Each rule inspects the latest snapshot and returns at most one ProposedAction
(or None). Rules are PURE: no I/O, no mutation. They read the snapshot only.
EXCEPTION: window-gated rules (§10.3 self-offload) read the wall clock to test
overnight-window membership via the pure helper `_in_overnight_window(prefs, now)`
— a documented, deterministic-given-`now` read, same category as stamping
proposed_at. All other inputs (VRAM pressure, T1 offload state) come from the
snapshot, written by the listeners. The engine handles cooldown/dedup and routes
proposals through the authority gate.

P3.1 shipped ONE rule (the seed). The T1-offload pair was added 2026-06-16
(operator goal) — see master_summary §10.3 / §12.6. The §10.3 burst-eviction
rung (evict_idle_burst_under_pressure) was added 2026-06-28: it reclaims an idle
burst tier's GPU VRAM before the last-resort T1 offload, idle-guarded by the
tier_health /slots probe (runtime.active_requests).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Callable, List

from .schema import (
    BURST_TIERS,
    CPU_DATAPLANE_TIERS,
    FLAP_THRESHOLD_24H,
    HealthStatus,
    OOMRisk,
    ProposedAction,
    SystemModel,
    TierState,
)

Rule = Callable[[SystemModel], List[ProposedAction]]

# Crash detection reconciled against disk (P3.1 execution):
#   • tier_health.py sets runtime.state = FAILED on an ACTIVE→unresponsive
#     transition. BUT it only clears FAILED via STOPPED→ACTIVE, so FAILED is
#     STICKY: a tier that crashed once and recovered stays state=FAILED while
#     health_status returns to OK. (Verified on disk: t3/t5 both sat at
#     state=failed / health_status=ok for ~15h while serving fine.)
#   • Therefore state alone is NOT a live crash signal — we AND it with the
#     live health_status==UNRESPONSIVE. Both are set together by tier_health on
#     a genuine crash; the sticky-but-healthy case (health_status==ok) is
#     correctly excluded, so we never spuriously bounce a healthy tier.
#   • process.py owns restart_count_24h; _FLAP_THRESHOLD mirrors its value.
# (The brief referenced runtime.last_pid, which does not exist — the schema
# field is runtime.pid, None during a crash, so it cannot discriminate
# incidents. The engine's cooldown handles "one incident counts once" instead.)
_CRASHED_STATE = TierState.FAILED
_DOWN_HEALTH = HealthStatus.UNRESPONSIVE
_FLAP_THRESHOLD = FLAP_THRESHOLD_24H     # shared single source (schema.py)
_SEED_TIERS = CPU_DATAPLANE_TIERS        # derived from MONARCH_TIERS (cpu_only & enabled)
_BURST_TIERS = BURST_TIERS               # derived from MONARCH_TIERS (burst_only & enabled)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local_now() -> datetime:
    """System-local timezone-aware now — the frame the overnight window is tested
    in (§9.5.3). Isolated as a helper so window-gated rules are deterministically
    testable without monkeypatching the datetime class."""
    return datetime.now().astimezone()


# §10.3 Substrate Pressure Cascade — T1 self-offload triggers on the existing
# OOM-pressure signal (vram.py owns oom_risk; ELEVATED/IMMINENT = headroom tight).
_VRAM_PRESSURE = (OOMRisk.ELEVATED, OOMRisk.IMMINENT)

# Below this much GPU VRAM, T4 has no meaningful step-down headroom to reclaim
# (it is CPU-resident at 0 MiB since 2026-06-16 §5.4, so this rung is inert today;
# kept for forward-compat if T4 ever returns to GPU).
_T4_STEPDOWN_FLOOR_MB = 1000


def _higher_cascade_rung_available(model: SystemModel) -> bool:
    """Canon §10.3 / §11.5 precedence: evict T2 burst → evict T6 burst → step T4
    down BEFORE T1 is touched. Returns True while any higher-priority VRAM reclaim
    is still available, in which case T1 self-offload must DEFER — it is the LAST
    resort, not the first response. A burst tier holding GPU VRAM is reclaimable
    headroom that canon spends before reaching T1; T4 step-down is inert while T4
    is CPU-resident (0 MiB).

    A burst on GPU is a reclaimable higher rung ONLY while it is IDLE
    (active_requests == 0): the eviction rung (evict_idle_burst_under_pressure +
    evict_idle_burst_tier, 2026-06-28) reclaims it first, so T1 defers. A BUSY
    burst (active_requests > 0) is NOT reclaimable and must NOT park T1 offload —
    per §5.8 the T1 self-offload EXISTS precisely to give an active burst headroom
    (it is the documented coexistence config), so under pressure T1 degrades to
    feed the burst rather than deadlocking with no move. Unknown activity
    (active_requests is None — /slots unavailable) is likewise treated as
    non-reclaimable: prefer the sanctioned, reversible T1 offload over a stall.
    T4 step-down remains §12 seed-engine future work (inert today). The operator's
    explicit ~/bin/t1-offload is unaffected."""
    ubt = model.resources.vram.used_by_tier
    for tid in BURST_TIERS:                          # idle burst on GPU → evict it first
        t = model.tiers.get(tid)
        if t is not None and getattr(ubt, tid, 0) > 0 and t.runtime.active_requests == 0:
            return True
    if ubt.t4 > _T4_STEPDOWN_FLOOR_MB:   # T4 has GPU headroom to step down first
        return True
    return False


def _in_overnight_window(prefs, now_local: datetime) -> bool:
    """True iff now_local falls in the overnight offload window leading into a
    weekday (Mon–Fri). The window wraps midnight (e.g. 23:00→07:00): the evening
    side counts the NEXT day as the workday, the morning side counts today.
    Weekend nights/mornings are excluded (canon §9.5.3: weekday baseline; weekend
    deferred). Pure given `now_local`."""
    try:
        sh, sm = (int(x) for x in prefs.overnight_window_start.split(":"))
        eh, em = (int(x) for x in prefs.overnight_window_end.split(":"))
    except (ValueError, AttributeError):
        return False
    start, end = time(sh, sm), time(eh, em)
    t = now_local.time()
    wraps = start > end
    in_span = ((t >= start or t < end) if wraps else (start <= t < end))
    if not in_span:
        return False
    if wraps and t >= start:
        workday = (now_local + timedelta(days=1)).weekday()   # evening → tomorrow
    else:
        workday = now_local.weekday()                          # morning → today
    return workday < 5   # Mon..Fri


def vram_pressure_offload_t1(model: SystemModel) -> List[ProposedAction]:
    """§10.3: under VRAM pressure inside the overnight weekday window, propose
    offloading a portion of T1 GPU→CPU/DDR5. The gate fires this as a NON-BLOCKING
    Tier-3 action (120s veto window, then default-proceed). Never fires during
    weekday working hours, if T1 is already offloaded, or while a higher rung is
    RECLAIMABLE — an IDLE burst on GPU (eviction reclaims it first) or T4
    step-down headroom (§10.3/§11.5 precedence; T1 is the last resort). It DOES
    fire when the burst holding GPU is BUSY: per §5.8 the offload exists to give
    an active burst headroom, so T1 degrades to feed it rather than stalling.
    Cooldown + prune handle re-proposal / condition-clear."""
    t1 = model.tiers.get("t1")
    if t1 is None or t1.runtime.offloaded:
        return []
    if model.resources.vram.oom_risk not in _VRAM_PRESSURE:
        return []
    if _higher_cascade_rung_available(model):
        return []                        # canon: spend the higher rungs first
    if not _in_overnight_window(model.operator.preferences, _local_now()):
        return []
    return [ProposedAction(
        action_id="offload_t1_reasoning",
        trigger=f"vram:pressure:{model.resources.vram.oom_risk.value}",
        params={},
        dedup_key="offload_t1_reasoning",
        rationale=("VRAM pressure persists in the overnight window; offloading a "
                   "portion of T1 to RAM to free headroom for the burst"),
        proposed_at=_utcnow(),
    )]


def restore_t1_when_window_closes(model: SystemModel) -> List[ProposedAction]:
    """§10.3 reverse: T1 is offloaded but we are no longer in the overnight
    weekday window → restore full GPU residency (Tier-2 autonomous-with-log).
    Idempotent via ~/bin/t1-restore + the marker, so one proposal suffices."""
    t1 = model.tiers.get("t1")
    if t1 is None or not t1.runtime.offloaded:
        return []
    if _in_overnight_window(model.operator.preferences, _local_now()):
        return []
    return [ProposedAction(
        action_id="restore_t1_reasoning",
        trigger="overnight_window_closed",
        params={},
        dedup_key="restore_t1_reasoning",
        rationale="overnight window closed; restoring T1 to full GPU residency",
        proposed_at=_utcnow(),
    )]


def crashed_cpu_tier(model: SystemModel) -> List[ProposedAction]:
    """Seed rule: a CPU dataplane tier (T3/T4/T5 — the cpu_only & enabled set) is
    crashed RIGHT NOW (state FAILED AND health_status UNRESPONSIVE) and is not
    flapping (restart_count_24h < 3).
    Proposes an idempotent single-tier restart PER crashed tier — a simultaneous
    t3+t5 crash yields two proposals (distinct dedup_keys), so neither masks the
    other. The engine's per-dedup_key cooldown prevents re-proposing while a
    condition persists."""
    out: List[ProposedAction] = []
    for tid in _SEED_TIERS:
        t = model.tiers.get(tid)
        if t is None:
            continue
        rt = t.runtime
        if (rt.state == _CRASHED_STATE
                and rt.health_status == _DOWN_HEALTH
                and rt.restart_count_24h < _FLAP_THRESHOLD):
            out.append(ProposedAction(
                action_id="auto_restart_cpu_dataplane_tier",
                trigger=f"tier_health:tier_crashed:{tid}",
                params={"tier": tid},
                dedup_key=f"auto_restart_cpu_dataplane_tier:{tid}",
                rationale=f"{tid} crashed (state=failed); idempotent restart via t{tid[-1]}-up",
                proposed_at=_utcnow(),
            ))
    return out


def evict_idle_burst_under_pressure(model: SystemModel) -> List[ProposedAction]:
    """§10.3 cascade rung 1: under VRAM pressure, evict an UP burst tier that is
    IDLE (zero in-flight requests, from the tier_health /slots probe) GPU→down to
    reclaim its VRAM BEFORE the last-resort T1 self-offload.

    Fires ANY time pressure holds — not window-gated, unlike T1 offload (§3.3 #3
    'pause is not in the toolkit; re-route always': an idle burst must not squat
    GPU VRAM under pressure). Idle-guarded: a burst that is busy
    (active_requests > 0) or whose activity is UNKNOWN (None — /slots
    unavailable) is never proposed, so live burst work is never killed. Per-tier
    dedup_key; the engine's cooldown/prune handle re-proposal and condition-clear.
    Cold-starts Tier 3 (operator-gated 'react when present') and earns Tier 2
    (autonomous 'prevent collapse') via the N=12 ladder."""
    if model.resources.vram.oom_risk not in _VRAM_PRESSURE:
        return []
    out: List[ProposedAction] = []
    ubt = model.resources.vram.used_by_tier
    for tid in _BURST_TIERS:
        t = model.tiers.get(tid)
        if t is None:
            continue
        if getattr(ubt, tid, 0) <= 0:          # not holding GPU VRAM → nothing to reclaim
            continue
        if t.runtime.active_requests != 0:     # busy (>0) or unknown (None) → don't evict
            continue
        out.append(ProposedAction(
            action_id="evict_idle_burst_tier",
            trigger=f"vram:pressure:{model.resources.vram.oom_risk.value}",
            params={"tier": tid},
            dedup_key=f"evict_idle_burst_tier:{tid}",
            rationale=(f"VRAM pressure; {tid} burst is idle (0 in-flight) and holding GPU "
                       f"— evict to reclaim headroom before the last-resort T1 offload"),
            proposed_at=_utcnow(),
        ))
    return out


# Cascade order: reclaim idle burst VRAM (rung 1) before the last-resort T1
# self-offload (rung 4); restart sits outside the VRAM cascade.
RULES: List[Rule] = [
    crashed_cpu_tier,
    evict_idle_burst_under_pressure,
    vram_pressure_offload_t1,
    restore_t1_when_window_closes,
]
