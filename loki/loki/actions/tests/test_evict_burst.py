"""EvictIdleBurstTier execute-time freshness guard (§10.3 idle-only, hardened).

The rule idle-guards off the snapshot, which lags the /slots probe by up to one
tier_health sweep (~15s). With the action now autonomous (non-blocking veto
window), a burst that started serving inside that window could otherwise be
evicted. So execute() RE-PROBES /slots fresh immediately before t{n}-down and
aborts unless the burst is provably idle (active_requests == 0) — busy (>0) or
unknown (None) → refuse, never kill live work.
"""

from loki.actions import evict_burst
from loki.actions.evict_burst import EvictIdleBurstTier


class _FakeProc:
    def __init__(self, rc=0):
        self.returncode = rc
        self.stdout = ""
        self.stderr = ""


def _spy_subprocess(monkeypatch):
    state = {"ran": False}

    def fake_run(*a, **k):
        state["ran"] = True
        return _FakeProc(0)

    monkeypatch.setattr(evict_burst.subprocess, "run", fake_run)
    return state


def test_execute_aborts_when_burst_busy_at_dispatch(monkeypatch):
    monkeypatch.setattr(evict_burst, "_slots_active_count", lambda port, **k: 1)
    ran = _spy_subprocess(monkeypatch)
    out = EvictIdleBurstTier().execute({"tier": "t2"})
    assert out == "failed"
    assert ran["ran"] is False   # t{n}-down must NOT have run


def test_execute_aborts_when_activity_unknown(monkeypatch):
    monkeypatch.setattr(evict_burst, "_slots_active_count", lambda port, **k: None)
    ran = _spy_subprocess(monkeypatch)
    out = EvictIdleBurstTier().execute({"tier": "t2"})
    assert out == "failed"
    assert ran["ran"] is False


def test_execute_proceeds_when_idle_at_dispatch(monkeypatch):
    monkeypatch.setattr(evict_burst, "_slots_active_count", lambda port, **k: 0)
    ran = _spy_subprocess(monkeypatch)
    out = EvictIdleBurstTier().execute({"tier": "t2"})
    assert out == "ok"
    assert ran["ran"] is True    # idle → bring-down ran
