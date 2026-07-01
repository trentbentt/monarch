"""HardwareListener: GPU telemetry parsing, thermal thresholds, graceful
degradation when probe surfaces are absent, and thermal transition events."""

from loki.listeners import hardware as hw
from loki.listeners.hardware import HardwareListener, _thermal_state
from loki.schema import SystemModel


class _FakeStore:
    def __init__(self):
        self.model = SystemModel()
        self.emitted = []

    def apply(self, fn, timeout=1.0):
        fn(self.model)
        return True

    def emit(self, **kw):
        self.emitted.append(kw)


def _patch_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(hw.StateStore, "get", classmethod(lambda cls: store))
    return store


def test_gpu_telemetry_parse(monkeypatch):
    monkeypatch.setattr(hw, "_run", lambda *a, **k: "55, 30, 80, 250.5, 12000")
    data, note = hw._gpu_telemetry()
    assert note is None
    assert data == {
        "temperature_c": 55, "fan_percent": 30, "utilization_percent": 80,
        "power_watts": 250.5, "memory_used_mb": 12000,
    }


def test_gpu_telemetry_handles_na_fan(monkeypatch):
    # Fan-stop / headless cards report '[N/A]' — must parse to None, not crash.
    monkeypatch.setattr(hw, "_run", lambda *a, **k: "40, [N/A], 0, 14.1, 600")
    data, note = hw._gpu_telemetry()
    assert note is None
    assert data["fan_percent"] is None
    assert data["temperature_c"] == 40


def test_gpu_telemetry_unavailable(monkeypatch):
    monkeypatch.setattr(hw, "_run", lambda *a, **k: None)
    data, note = hw._gpu_telemetry()
    assert data is None
    assert "unavailable" in note


def test_thermal_state_thresholds():
    assert _thermal_state(None) == "unknown"
    assert _thermal_state(82) == "ok"
    assert _thermal_state(83) == "warn"
    assert _thermal_state(89) == "warn"
    assert _thermal_state(90) == "critical"


def test_poll_writes_health_and_degrades_gracefully(monkeypatch):
    store = _patch_store(monkeypatch)
    monkeypatch.setattr(hw, "_gpu_telemetry", lambda: (
        {"temperature_c": 85, "fan_percent": 60, "utilization_percent": 95,
         "power_watts": 300.0, "memory_used_mb": 20000}, None))
    monkeypatch.setattr(hw, "_disk_smart",
                        lambda: ("unavailable", None, "smartctl not installed"))
    monkeypatch.setattr(hw, "_ram_ecc",
                        lambda: ("unavailable", None, None, "no EDAC controller"))

    HardwareListener().poll()

    h = store.model.hardware.health
    assert h.gpu.temperature_c == 85
    assert h.gpu.thermal_state == "warn"
    assert h.disk_smart == "unavailable"
    assert h.ram_ecc_status == "unavailable"
    assert any("disk:" in n for n in h.notes)
    assert any("ram:" in n for n in h.notes)
    # warn is a fresh transition from the ok baseline → one thermal event.
    assert any(e["type"] == "gpu_thermal" and e["severity"] == "warning"
               for e in store.emitted)


def test_poll_no_event_when_thermal_steady(monkeypatch):
    store = _patch_store(monkeypatch)
    monkeypatch.setattr(hw, "_gpu_telemetry", lambda: (
        {"temperature_c": 40, "fan_percent": 0, "utilization_percent": 0,
         "power_watts": 14.0, "memory_used_mb": 600}, None))
    monkeypatch.setattr(hw, "_disk_smart", lambda: ("unavailable", None, None))
    monkeypatch.setattr(hw, "_ram_ecc", lambda: ("unavailable", None, None, None))

    listener = HardwareListener()
    listener.poll()
    listener.poll()
    assert not store.emitted  # steady 'ok' never emits


def test_poll_survives_nvidia_smi_absent(monkeypatch):
    store = _patch_store(monkeypatch)
    monkeypatch.setattr(hw, "_run", lambda *a, **k: None)  # all probes blind
    HardwareListener().poll()  # must not raise
    h = store.model.hardware.health
    assert h.gpu.thermal_state == "unknown"
    assert any("gpu:" in n for n in h.notes)
