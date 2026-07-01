"""
Hardware Listener v0.1

Samples live host hardware telemetry the rest of the stack is otherwise blind to
(§16.8 observability gap):

  - GPU thermals / fan / utilisation / power / memory  (nvidia-smi)
  - Disk SMART overall-health                          (smartctl, best effort)
  - RAM ECC correctable/uncorrectable counters         (EDAC sysfs, best effort)

Writes `model.hardware.health` via StateStore.apply() — never holds the model
lock. Every probe degrades gracefully: when a surface is absent (no smartctl
binary, no EDAC memory controller, no nvidia-smi) the listener records a note and
reports an 'unavailable'/'unknown' status instead of raising. Emits coarse
transition events for GPU thermal escalation and SMART failure.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from .base import BaseListener
from .util import run_cmd
from ..state import StateStore

logger = logging.getLogger(__name__)

# RTX 3090 FE edge-temp thresholds. Ampere begins throttling ~83C; >=90C is the
# danger band where sustained load risks instability.
_GPU_TEMP_WARN = 83
_GPU_TEMP_CRIT = 90

_EDAC_MC_DIR = "/sys/devices/system/edac/mc"


def _run(cmd: list[str], timeout: float = 3.0) -> Optional[str]:
    # Hardware probes want stripped stdout. Subprocess boilerplate shared in
    # util.run_cmd (a missing binary / timeout / OSError → None, a note).
    return run_cmd(cmd, timeout, strip=True)


def _read_int(path: str) -> Optional[int]:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _gpu_telemetry() -> Tuple[Optional[dict], Optional[str]]:
    """Return ({temperature_c, fan_percent, utilization_percent, power_watts,
    memory_used_mb}, None) or (None, note). Single-GPU box: first row only."""
    out = _run([
        "nvidia-smi",
        "--query-gpu=temperature.gpu,fan.speed,utilization.gpu,power.draw,memory.used",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return None, "nvidia-smi unavailable"
    parts = [p.strip() for p in out.splitlines()[0].split(",")]
    if len(parts) != 5:
        return None, f"nvidia-smi parse error: {out.splitlines()[0]!r}"

    def _i(x: str) -> Optional[int]:
        try:
            return int(float(x))
        except ValueError:
            return None  # e.g. fan '[N/A]' on fan-stop / headless cards

    def _f(x: str) -> Optional[float]:
        try:
            return float(x)
        except ValueError:
            return None

    temp, fan, util, power, mem = parts
    return {
        "temperature_c": _i(temp),
        "fan_percent": _i(fan),
        "utilization_percent": _i(util),
        "power_watts": _f(power),
        "memory_used_mb": _i(mem),
    }, None


def _thermal_state(temp: Optional[int]) -> str:
    if temp is None:
        return "unknown"
    if temp >= _GPU_TEMP_CRIT:
        return "critical"
    if temp >= _GPU_TEMP_WARN:
        return "warn"
    return "ok"


def _block_devices() -> List[str]:
    out = _run(["lsblk", "-dno", "NAME,TYPE"])
    if not out:
        return []
    devs = []
    for ln in out.splitlines():
        f = ln.split()
        if len(f) >= 2 and f[1] == "disk":
            devs.append(f[0])
    return devs


def _disk_smart() -> Tuple[str, Optional[str], Optional[str]]:
    """Best-effort SMART summary. Returns (status, detail, note).
    status: ok | failing | unavailable | unknown."""
    if _run(["smartctl", "--version"]) is None:
        return "unavailable", None, "smartctl not installed (apt install smartmontools)"
    devs = _block_devices()
    if not devs:
        return "unknown", None, "no block devices detected"
    parts: List[str] = []
    overall = "ok"
    for dev in devs:
        out = _run(["smartctl", "-H", f"/dev/{dev}"])
        if out is None:
            parts.append(f"{dev}:unreadable")
            if overall == "ok":
                overall = "unknown"
            continue
        low = out.lower()
        if "failed" in low:
            parts.append(f"{dev}:FAILED")
            overall = "failing"
        elif "passed" in low or "ok" in low:
            parts.append(f"{dev}:ok")
        else:
            parts.append(f"{dev}:?")
            if overall == "ok":
                overall = "unknown"
    return overall, " ".join(parts), None


def _ram_ecc() -> Tuple[str, Optional[int], Optional[int], Optional[str]]:
    """Read EDAC correctable/uncorrectable counters across memory controllers.
    Returns (status, correctable, uncorrectable, note).
    status: ok | errors | unavailable."""
    if not os.path.isdir(_EDAC_MC_DIR):
        return "unavailable", None, None, "no EDAC subsystem"
    mcs = [d for d in os.listdir(_EDAC_MC_DIR)
           if d.startswith("mc") and d[2:].isdigit()]
    if not mcs:
        return "unavailable", None, None, "no EDAC memory controller (ECC not exposed)"
    ce = ue = 0
    for mc in mcs:
        ce += _read_int(os.path.join(_EDAC_MC_DIR, mc, "ce_count")) or 0
        ue += _read_int(os.path.join(_EDAC_MC_DIR, mc, "ue_count")) or 0
    return ("errors" if (ce or ue) else "ok"), ce, ue, None


class HardwareListener(BaseListener):
    name = "hardware"
    interval_sec = 30.0

    def __init__(self) -> None:
        super().__init__()
        self._last_thermal = "ok"
        self._last_disk = "ok"

    def poll(self) -> None:
        now = datetime.now(timezone.utc)
        store = StateStore.get()
        notes: List[str] = []

        gpu, gnote = _gpu_telemetry()
        if gnote:
            notes.append(f"gpu: {gnote}")
        temp = gpu["temperature_c"] if gpu else None
        thermal = _thermal_state(temp)

        disk_status, disk_detail, dnote = _disk_smart()
        if dnote:
            notes.append(f"disk: {dnote}")

        ecc_status, ce, ue, enote = _ram_ecc()
        if enote:
            notes.append(f"ram: {enote}")

        def update(model):
            h = model.hardware.health
            g = h.gpu
            if gpu:
                g.temperature_c = gpu["temperature_c"]
                g.fan_percent = gpu["fan_percent"]
                g.utilization_percent = gpu["utilization_percent"]
                g.power_watts = gpu["power_watts"]
                g.memory_used_mb = gpu["memory_used_mb"]
            g.thermal_state = thermal
            h.disk_smart = disk_status
            h.disk_detail = disk_detail
            h.ram_ecc_status = ecc_status
            h.ram_ecc_correctable = ce
            h.ram_ecc_uncorrectable = ue
            h.updated_at = now
            h.notes = notes

        store.apply(update)

        # GPU thermal transitions (coarse state gives natural hysteresis).
        if thermal != self._last_thermal:
            if thermal in ("warn", "critical"):
                store.emit(
                    type="gpu_thermal",
                    severity="critical" if thermal == "critical" else "warning",
                    detail=f"GPU {temp}C: {self._last_thermal} -> {thermal}",
                    temperature_c=temp,
                    thermal_state=thermal,
                )
            elif self._last_thermal in ("warn", "critical") and thermal == "ok":
                store.emit(
                    type="gpu_thermal_resolved", severity="info",
                    detail=f"GPU temp normalised to {temp}C",
                    temperature_c=temp,
                )
            self._last_thermal = thermal

        # SMART failure → critical, once per transition into 'failing'.
        if disk_status == "failing" and self._last_disk != "failing":
            store.emit(
                type="disk_smart_failing", severity="critical",
                detail=f"SMART health failing: {disk_detail}",
            )
        if disk_status in ("ok", "failing"):
            self._last_disk = disk_status

        if thermal == "critical":
            logger.warning("[hardware] GPU at %sC (critical)", temp)
