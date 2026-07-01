"""TierHealthListener probe fan-out: parallel, order-preserving, passthrough-safe.

These tests pin the M20 fix — per-component health probes run concurrently
instead of serializing behind each probe's timeout — without regressing the
output contract (component order and the port-None passthrough).
"""

import threading
import time
import types

from loki.listeners import tier_health as th
from loki.listeners.tier_health import TierHealthListener
from loki.schema import ComponentHealth, HealthStatus


def _comp(name, port, status=HealthStatus.UNKNOWN):
    return ComponentHealth(name=name, port=port, status=status)


class _FakeStore:
    """Minimal StateStore stand-in capturing the model mutated by apply()."""

    def __init__(self, components):
        self._components = components
        self.applied_model = None
        self.emitted = []

    def snapshot(self):
        return types.SimpleNamespace(
            health=types.SimpleNamespace(components=list(self._components)),
            tiers={},
        )

    def apply(self, fn, timeout=1.0):
        model = types.SimpleNamespace(
            health=types.SimpleNamespace(components=None, last_full_sweep=None),
            tiers={},
        )
        fn(model)
        self.applied_model = model
        return True

    def emit(self, **kw):
        self.emitted.append(kw)


def _run_poll(monkeypatch, components, probe_delay):
    """Drive one poll() with a fake store and an instrumented slow HTTP probe.

    Component names avoid _TIER_TO_COMPONENT so the tier/transition loops are
    no-ops and we exercise the fan-out path in isolation.
    """
    store = _FakeStore(components)
    monkeypatch.setattr(th.StateStore, "get", classmethod(lambda cls: store))

    state = {"active": 0, "max_active": 0}
    lock = threading.Lock()

    def slow_http(port, path, timeout=3.0, bearer_env=None):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        time.sleep(probe_delay)
        with lock:
            state["active"] -= 1
        return True, 5

    monkeypatch.setattr(th, "_http_check", slow_http)

    t0 = time.monotonic()
    TierHealthListener().poll()
    elapsed = time.monotonic() - t0
    return store, elapsed, state


def test_probes_run_concurrently(monkeypatch):
    # 8 probes each sleeping 0.2s would take ~1.6s serialized.
    comps = [_comp(f"svc-{i}", 9000 + i) for i in range(8)]
    store, elapsed, state = _run_poll(monkeypatch, comps, 0.2)
    assert elapsed < 0.8, f"probes appear serialized: {elapsed:.2f}s"
    assert state["max_active"] >= 2, "probes did not overlap"
    out = store.applied_model.health.components
    assert all(c.status == HealthStatus.OK for c in out)


def test_output_order_preserved(monkeypatch):
    comps = [_comp(f"svc-{i}", 9000 + i) for i in range(6)]
    store, _, _ = _run_poll(monkeypatch, comps, 0.0)
    names = [c.name for c in store.applied_model.health.components]
    assert names == [c.name for c in comps]


def test_port_none_component_passthrough(monkeypatch):
    comps = [_comp("svc-a", 9001), _comp("portless", None), _comp("svc-b", 9002)]
    store, _, _ = _run_poll(monkeypatch, comps, 0.0)
    out = {c.name: c for c in store.applied_model.health.components}
    # Port-None component is returned unchanged (never probed).
    assert out["portless"].status == HealthStatus.UNKNOWN
    assert out["svc-a"].status == HealthStatus.OK
    names = [c.name for c in store.applied_model.health.components]
    assert names == ["svc-a", "portless", "svc-b"]
