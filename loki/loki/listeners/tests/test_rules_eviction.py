"""§10.3 cascade rung-1 rule: evict an IDLE burst tier under VRAM pressure.

Also the first unit coverage of a rules.py decision function — the eviction rule
must (a) fire only under VRAM pressure, (b) only for a burst holding GPU VRAM,
and (c) only when the /slots probe proved it idle (active_requests == 0) — never
when busy (>0) or unknown (None), so an actively-serving burst is never killed.
"""

from loki.rules import evict_idle_burst_under_pressure
from loki.schema import MONARCH_TIERS, OOMRisk, SystemModel, Tier, TierRuntime


def _model(*, oom, t2_vram, active):
    m = SystemModel()
    m.resources.vram.oom_risk = oom
    m.resources.vram.used_by_tier.t2 = t2_vram
    m.tiers["t2"] = Tier(
        config=MONARCH_TIERS["t2"],
        runtime=TierRuntime(active_requests=active),
    )
    return m


def test_evicts_idle_burst_under_pressure():
    out = evict_idle_burst_under_pressure(_model(oom=OOMRisk.ELEVATED, t2_vram=6800, active=0))
    assert len(out) == 1
    p = out[0]
    assert p.action_id == "evict_idle_burst_tier"
    assert p.params == {"tier": "t2"}
    assert p.dedup_key == "evict_idle_burst_tier:t2"


def test_does_not_evict_busy_burst():
    assert evict_idle_burst_under_pressure(_model(oom=OOMRisk.IMMINENT, t2_vram=6800, active=1)) == []


def test_does_not_evict_unknown_activity():
    # active_requests None = /slots unavailable → UNKNOWN, must not be treated idle.
    assert evict_idle_burst_under_pressure(_model(oom=OOMRisk.ELEVATED, t2_vram=6800, active=None)) == []


def test_no_eviction_without_pressure():
    assert evict_idle_burst_under_pressure(_model(oom=OOMRisk.LOW, t2_vram=6800, active=0)) == []


def test_no_eviction_when_burst_off_gpu():
    assert evict_idle_burst_under_pressure(_model(oom=OOMRisk.ELEVATED, t2_vram=0, active=0)) == []
