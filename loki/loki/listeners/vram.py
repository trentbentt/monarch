"""
VRAM Listener v0.2

Polls nvidia-smi every 5s. Builds an update function and queues it via
StateStore.apply() — never holds the model lock directly.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from .base import BaseListener
from .util import _port_from_cmdline
from ..schema import OOMRisk, PORT_TO_TIER, VRAM_BASELINE
from ..state import StateStore

logger = logging.getLogger(__name__)

_OOM_ELEVATED_THRESHOLD_MB = 2000
_OOM_IMMINENT_THRESHOLD_MB = 500


def _run(cmd: list[str], timeout: float = 3.0) -> Optional[str]:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _get_total_vram() -> Optional[Tuple[int, int]]:
    out = _run([
        "nvidia-smi",
        "--query-gpu=memory.used,memory.free",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return None
    parts = [p.strip() for p in out.split(",")]
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _get_process_vram() -> Dict[int, int]:
    out = _run([
        "nvidia-smi",
        "--query-compute-apps=pid,used_gpu_memory",
        "--format=csv,noheader,nounits",
    ])
    result: Dict[int, int] = {}
    if not out:
        return result
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            result[int(parts[0])] = int(parts[1])
        except ValueError:
            continue
    return result


class VRAMListener(BaseListener):
    name = "vram"
    interval_sec = 5.0

    def __init__(self) -> None:
        super().__init__()
        self._last_oom_risk = OOMRisk.LOW

    def poll(self) -> None:
        now = datetime.now(timezone.utc)
        store = StateStore.get()

        total = _get_total_vram()
        if total is None:
            logger.warning("[vram] nvidia-smi total query failed")
            return

        used_mb, free_mb = total
        process_vram = _get_process_vram()

        tier_vram: Dict[str, int] = {t: 0 for t in PORT_TO_TIER.values()}
        tier_vram["other"] = 0
        driver_mb = VRAM_BASELINE.get("driver_display", 512)

        pid_to_tier: Dict[int, str] = {}
        for pid in process_vram:
            port = _port_from_cmdline(pid)
            if port and port in PORT_TO_TIER:
                pid_to_tier[pid] = PORT_TO_TIER[port]
            else:
                pid_to_tier[pid] = "other"

        for pid, mb in process_vram.items():
            tier_id = pid_to_tier.get(pid, "other")
            tier_vram[tier_id] = tier_vram.get(tier_id, 0) + mb

        if free_mb < _OOM_IMMINENT_THRESHOLD_MB:
            oom_risk = OOMRisk.IMMINENT
        elif free_mb < _OOM_ELEVATED_THRESHOLD_MB:
            oom_risk = OOMRisk.ELEVATED
        else:
            oom_risk = OOMRisk.LOW

        active_tiers = set(pid_to_tier.values()) - {"other"}

        def update(model):
            v = model.resources.vram
            v.used_mb = used_mb
            v.free_mb = free_mb
            v.oom_risk = oom_risk
            v.used_by_tier.t1 = tier_vram.get("t1", 0)
            v.used_by_tier.t2 = tier_vram.get("t2", 0)
            v.used_by_tier.t3 = tier_vram.get("t3", 0)
            v.used_by_tier.t4 = tier_vram.get("t4", 0)
            v.used_by_tier.t5 = tier_vram.get("t5", 0)
            v.used_by_tier.t6 = tier_vram.get("t6", 0)
            v.used_by_tier.driver_display = driver_mb
            v.used_by_tier.other = tier_vram.get("other", 0)
            v.updated_at = now

            for tier_id in ("t1", "t2", "t3", "t4", "t5", "t6"):
                if tier_id in model.tiers:
                    model.tiers[tier_id].resources.vram_used_mb = tier_vram.get(tier_id, 0)

            # NOTE: vram deliberately does NOT write tier.runtime.state. tier_health
            # is the single source of truth for the health-driven state machine and
            # is the only writer that emits the state-change events the Command
            # Center consumes. A second, event-less writer here raced tier_health
            # (vram polls 3x faster) and thrashed FAILED<->ACTIVE with no recovery
            # event during a wedged-but-PID-present tier (review H3). vram only
            # reports VRAM accounting; state transitions belong to tier_health.

        store.apply(update)

        if oom_risk != self._last_oom_risk:
            if oom_risk != OOMRisk.LOW:
                store.emit(
                    type="oom_risk_changed",
                    severity="warning" if oom_risk == OOMRisk.ELEVATED else "critical",
                    detail=f"OOM risk: {self._last_oom_risk.value} -> {oom_risk.value} (free: {free_mb} MiB)",
                    free_mb=free_mb,
                    used_mb=used_mb,
                    oom_risk=oom_risk.value,
                    previous_risk=self._last_oom_risk.value,
                )
            else:
                store.emit(
                    type="oom_risk_resolved",
                    severity="info",
                    detail=f"OOM risk cleared: {self._last_oom_risk.value} -> low (free: {free_mb} MiB)",
                    free_mb=free_mb,
                )
            self._last_oom_risk = oom_risk
