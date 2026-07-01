"""VRAM listener must NOT write tier.runtime.state (review H3).

tier_health is the single source of truth for the health-driven state machine
and the only writer that emits the state-change events the Command Center
consumes. vram polls 3x faster; a second, event-less writer here raced it and
thrashed a wedged-but-PID-present tier FAILED<->ACTIVE with no recovery event.
This pins that vram only does VRAM accounting and leaves tier state to
tier_health.
"""
import types

from loki.listeners import vram as V
from loki.listeners.vram import VRAMListener
from loki.schema import TierState


def _model_with_failed_tier():
    def _tier():
        return types.SimpleNamespace(
            config=types.SimpleNamespace(enabled=True),
            runtime=types.SimpleNamespace(state=TierState.FAILED),
            resources=types.SimpleNamespace(vram_used_mb=0),
        )
    used_by_tier = types.SimpleNamespace(
        t1=0, t2=0, t3=0, t4=0, t5=0, t6=0, driver_display=0, other=0)
    vram = types.SimpleNamespace(
        used_mb=0, free_mb=0, oom_risk=None, used_by_tier=used_by_tier,
        updated_at=None)
    return types.SimpleNamespace(
        resources=types.SimpleNamespace(vram=vram),
        tiers={"t2": _tier()},
    )


class _CapturingStore:
    def __init__(self, model):
        self._model = model
        self.emitted = []

    def apply(self, fn, timeout=1.0):
        fn(self._model)
        return True

    def emit(self, **kw):
        self.emitted.append(kw)


def test_vram_does_not_resurrect_tier_state(monkeypatch):
    """A FAILED tier whose process IS present (PID → 'active') must stay FAILED:
    vram reports VRAM accounting but does not move tier state without an event.
    Pre-fix this flipped FAILED→ACTIVE silently."""
    t2_port = next(p for p, t in V.PORT_TO_TIER.items() if t == "t2")
    model = _model_with_failed_tier()
    store = _CapturingStore(model)
    monkeypatch.setattr(V.StateStore, "get", classmethod(lambda cls: store))
    monkeypatch.setattr(V, "_get_total_vram", lambda: (10000, 8000))   # plenty free
    monkeypatch.setattr(V, "_get_process_vram", lambda: {4242: 1500})  # t2's pid present
    monkeypatch.setattr(V, "_port_from_cmdline", lambda pid: t2_port)

    VRAMListener().poll()

    assert model.tiers["t2"].runtime.state == TierState.FAILED, \
        "vram resurrected tier state without an event (review H3 regression)"
    # it still did its real job — t2's VRAM was accounted
    assert model.tiers["t2"].resources.vram_used_mb == 1500
