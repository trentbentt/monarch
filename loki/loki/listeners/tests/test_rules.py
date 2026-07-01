"""Unit coverage for the rules.py decision functions — the core of the §10.3
collapse-prevention cascade and the §12.6 reaction loop. Before 2026-06-28 only
the eviction rule had tests; this backfills the rest and pins the busy-burst fix
to _higher_cascade_rung_available.

Window-gated rules are tested by monkeypatching rules._in_overnight_window so the
cascade/pressure logic is exercised deterministically, independent of wall clock.
The window math itself (_in_overnight_window) is covered separately and purely.
"""

from datetime import datetime

from loki import rules
from loki.schema import (
    CPU_DATAPLANE_TIERS,
    HealthStatus,
    MONARCH_TIERS,
    OOMRisk,
    SystemModel,
    Tier,
    TierRuntime,
    TierState,
)


# ── _higher_cascade_rung_available (the busy-burst fix) ──────────────────────
def _rung_model(*, t2_vram=0, t2_active=None, t4_vram=0):
    m = SystemModel()
    m.resources.vram.used_by_tier.t2 = t2_vram
    m.resources.vram.used_by_tier.t4 = t4_vram
    if t2_vram > 0 or t2_active is not None:
        m.tiers["t2"] = Tier(config=MONARCH_TIERS["t2"],
                             runtime=TierRuntime(active_requests=t2_active))
    return m


def test_idle_burst_is_a_reclaimable_rung_defers_t1():
    # idle burst on GPU → eviction reclaims it first → T1 defers
    assert rules._higher_cascade_rung_available(_rung_model(t2_vram=6800, t2_active=0)) is True


def test_busy_burst_is_not_reclaimable_does_not_defer_t1():
    # §5.8: T1 offload EXISTS to give an active burst headroom — a busy burst must
    # not park T1 offload (that was the residual deadlock).
    assert rules._higher_cascade_rung_available(_rung_model(t2_vram=6800, t2_active=3)) is False


def test_unknown_burst_activity_does_not_defer_t1():
    # active_requests None (/slots unavailable) = UNKNOWN → don't stall; let T1
    # offload proceed rather than deadlock under pressure.
    assert rules._higher_cascade_rung_available(_rung_model(t2_vram=6800, t2_active=None)) is False


def test_no_burst_no_higher_rung():
    assert rules._higher_cascade_rung_available(_rung_model()) is False


def test_t4_gpu_headroom_is_a_higher_rung():
    assert rules._higher_cascade_rung_available(_rung_model(t4_vram=2000)) is True


# ── vram_pressure_offload_t1 ─────────────────────────────────────────────────
def _t1_model(*, offloaded=False, oom=OOMRisk.ELEVATED, t2_vram=0, t2_active=None):
    m = SystemModel()
    m.resources.vram.oom_risk = oom
    m.resources.vram.used_by_tier.t2 = t2_vram
    m.tiers["t1"] = Tier(config=MONARCH_TIERS["t1"],
                        runtime=TierRuntime(offloaded=offloaded))
    if t2_vram > 0 or t2_active is not None:
        m.tiers["t2"] = Tier(config=MONARCH_TIERS["t2"],
                            runtime=TierRuntime(active_requests=t2_active))
    return m


def test_offload_fires_when_busy_burst_holds_gpu(monkeypatch):
    monkeypatch.setattr(rules, "_in_overnight_window", lambda p, n: True)
    out = rules.vram_pressure_offload_t1(_t1_model(t2_vram=6800, t2_active=2))
    assert len(out) == 1 and out[0].action_id == "offload_t1_reasoning"


def test_offload_defers_when_idle_burst_holds_gpu(monkeypatch):
    monkeypatch.setattr(rules, "_in_overnight_window", lambda p, n: True)
    # idle burst → eviction rung reclaims it first, T1 waits
    assert rules.vram_pressure_offload_t1(_t1_model(t2_vram=6800, t2_active=0)) == []


def test_offload_fires_with_no_burst(monkeypatch):
    monkeypatch.setattr(rules, "_in_overnight_window", lambda p, n: True)
    assert len(rules.vram_pressure_offload_t1(_t1_model(t2_vram=0))) == 1


def test_offload_skips_outside_window(monkeypatch):
    monkeypatch.setattr(rules, "_in_overnight_window", lambda p, n: False)
    assert rules.vram_pressure_offload_t1(_t1_model(t2_vram=0)) == []


def test_offload_skips_when_already_offloaded(monkeypatch):
    monkeypatch.setattr(rules, "_in_overnight_window", lambda p, n: True)
    assert rules.vram_pressure_offload_t1(_t1_model(offloaded=True)) == []


def test_offload_skips_without_pressure(monkeypatch):
    monkeypatch.setattr(rules, "_in_overnight_window", lambda p, n: True)
    assert rules.vram_pressure_offload_t1(_t1_model(oom=OOMRisk.LOW)) == []


# ── crashed_cpu_tier ─────────────────────────────────────────────────────────
def _cpu_model(tid, *, state, health, restarts=0):
    m = SystemModel()
    m.tiers[tid] = Tier(
        config=MONARCH_TIERS[tid],
        runtime=TierRuntime(state=state, health_status=health,
                            restart_count_24h=restarts),
    )
    return m


def test_crashed_cpu_tier_proposes_restart():
    tid = CPU_DATAPLANE_TIERS[0]
    out = rules.crashed_cpu_tier(_cpu_model(tid, state=TierState.FAILED,
                                            health=HealthStatus.UNRESPONSIVE))
    assert len(out) == 1
    assert out[0].action_id == "auto_restart_cpu_dataplane_tier"
    assert out[0].params == {"tier": tid}


def test_crashed_cpu_tier_skips_flapping():
    tid = CPU_DATAPLANE_TIERS[0]
    assert rules.crashed_cpu_tier(_cpu_model(tid, state=TierState.FAILED,
                                             health=HealthStatus.UNRESPONSIVE,
                                             restarts=3)) == []


def test_crashed_cpu_tier_skips_sticky_failed_but_healthy():
    # FAILED state but health OK (sticky-failed, serving fine) → not a live crash
    tid = CPU_DATAPLANE_TIERS[0]
    assert rules.crashed_cpu_tier(_cpu_model(tid, state=TierState.FAILED,
                                             health=HealthStatus.OK)) == []


# ── restore_t1_when_window_closes ────────────────────────────────────────────
def _restore_model(*, offloaded):
    m = SystemModel()
    m.tiers["t1"] = Tier(config=MONARCH_TIERS["t1"],
                        runtime=TierRuntime(offloaded=offloaded))
    return m


def test_restore_fires_when_offloaded_and_window_closed(monkeypatch):
    monkeypatch.setattr(rules, "_in_overnight_window", lambda p, n: False)
    out = rules.restore_t1_when_window_closes(_restore_model(offloaded=True))
    assert len(out) == 1 and out[0].action_id == "restore_t1_reasoning"


def test_restore_skips_inside_window(monkeypatch):
    monkeypatch.setattr(rules, "_in_overnight_window", lambda p, n: True)
    assert rules.restore_t1_when_window_closes(_restore_model(offloaded=True)) == []


def test_restore_skips_when_not_offloaded(monkeypatch):
    monkeypatch.setattr(rules, "_in_overnight_window", lambda p, n: False)
    assert rules.restore_t1_when_window_closes(_restore_model(offloaded=False)) == []


# ── _in_overnight_window (pure window math) ──────────────────────────────────
class _Prefs:
    overnight_window_start = "23:00"
    overnight_window_end = "07:00"


def test_window_weekday_overnight_morning_in():
    mon = datetime(2026, 6, 29, 2, 0)   # Monday 02:00
    assert mon.weekday() == 0
    assert rules._in_overnight_window(_Prefs(), mon) is True


def test_window_weekday_daytime_out():
    wed = datetime(2026, 6, 24, 14, 0)  # Wednesday 14:00
    assert wed.weekday() == 2
    assert rules._in_overnight_window(_Prefs(), wed) is False


def test_window_weekend_excluded():
    sat = datetime(2026, 6, 27, 2, 0)   # Saturday 02:00 → in time span, but weekend
    assert sat.weekday() == 5
    assert rules._in_overnight_window(_Prefs(), sat) is False
