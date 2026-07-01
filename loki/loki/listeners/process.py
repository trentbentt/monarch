"""
Process Listener v0.2

Per-tier process monitoring. Polls /proc every 30s. For each enabled tier:
discovers the tier's PID via port→tier cmdline matching (T3/T5 have no GPU PID
in nvidia-smi, so port-based discovery is mandatory), reads RSS / CPU% / uptime
from /proc, and detects restarts by PID change.

Spec: master_summary §12.4 ("process.py — per-tier process monitoring").

Ownership boundary: this listener owns the process-observation fields on
TierRuntime (pid, rss_mb, cpu_pct, uptime_sec, restart_count_24h,
last_restart_ts). It does NOT mutate runtime.state — tier_health.py is the
authority on tier liveness via health endpoints (a PID can exist while the
server is unresponsive). The 2-poll PID=None debounce guards restart-detection
accuracy, not a state transition.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .base import BaseListener
from .util import _port_from_cmdline
from ..schema import FLAP_THRESHOLD_24H, PORT_TO_TIER
from ..state import StateStore

logger = logging.getLogger(__name__)

_CLK_TCK = os.sysconf("SC_CLK_TCK")
_NONE_DEBOUNCE = 2                     # consecutive PID=None polls before treating process as gone
_FLAP_THRESHOLD = FLAP_THRESHOLD_24H  # restart_count_24h >= this → flapping (warning); shared (schema.py)
_RESTART_WINDOW = timedelta(hours=24)
_T1_OFFLOAD_MARKER = os.path.expanduser("~/.local/state/inference/t1_offload_marker")


def _t1_offload_state() -> Tuple[bool, Optional[int]]:
    """Read the T1 self-offload marker (§10.3, written by ~/bin/t1-offload).
    Returns (offloaded, reduced_ngl). The marker is the source of truth so the
    decision engine's rule stays a pure read of the snapshot."""
    try:
        with open(_T1_OFFLOAD_MARKER) as f:
            txt = f.read()
    except (FileNotFoundError, OSError):
        return False, None
    m = re.search(r"ngl=(\d+)", txt)
    return True, (int(m.group(1)) if m else None)


def _discover_tier_pids(self_pid: int) -> Dict[str, int]:
    """Scan /proc for processes whose --port maps to a monarch tier.

    Returns {tier_id: pid}. Excludes the Loki daemon (self_pid). Port-based
    discovery is mandatory: T3/T5 are CPU-only and never appear in nvidia-smi.
    """
    result: Dict[str, int] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return result
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == self_pid:
            continue
        port = _port_from_cmdline(pid)
        if port is None:
            continue
        tier_id = PORT_TO_TIER.get(port)
        if tier_id is not None:
            result[tier_id] = pid
    return result


def _read_rss_mb(pid: int) -> int:
    """VmRSS from /proc/{pid}/status, in MiB. 0 if unreadable."""
    try:
        with open(f"/proc/{pid}/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except (FileNotFoundError, ProcessLookupError, ValueError, IndexError):
        pass
    return 0


def _read_stat(pid: int) -> Optional[Tuple[int, int]]:
    """Return (utime+stime ticks, starttime ticks) from /proc/{pid}/stat.

    Handles a comm field containing spaces/parens by splitting after the final
    ')'. Field N (1-indexed) maps to rest[N-3] since rest[0] is field 3 (state).
    """
    try:
        with open(f"/proc/{pid}/stat", "r") as f:
            data = f.read()
    except (FileNotFoundError, ProcessLookupError):
        return None
    rparen = data.rfind(")")
    if rparen == -1:
        return None
    rest = data[rparen + 2:].split()
    try:
        utime = int(rest[11])      # field 14
        stime = int(rest[12])      # field 15
        starttime = int(rest[19])  # field 22
    except (IndexError, ValueError):
        return None
    return utime + stime, starttime


def _system_uptime() -> Optional[float]:
    """System uptime in seconds from /proc/uptime. None if unreadable."""
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.read().split()[0])
    except (FileNotFoundError, ValueError, IndexError):
        return None


class ProcessListener(BaseListener):
    name = "process"
    interval_sec = 30.0

    def __init__(self) -> None:
        super().__init__()
        self._tier_last_pid: Dict[str, Optional[int]] = {}
        self._tier_none_count: Dict[str, int] = {}
        self._tier_restarts: Dict[str, List[datetime]] = {}
        self._tier_last_cpu: Dict[str, Tuple[int, float]] = {}  # (total_ticks, monotonic_ts)

    def poll(self) -> None:
        now = datetime.now(timezone.utc)
        store = StateStore.get()
        snap = store.snapshot()

        self_pid = os.getpid()
        discovered = _discover_tier_pids(self_pid)
        sys_uptime = _system_uptime()
        t1_offloaded, t1_offload_ngl = _t1_offload_state()

        observations: Dict[str, dict] = {}
        restart_events: List[Tuple[str, int, Optional[int]]] = []  # (tier_id, count, pid)

        for tier_id, tier in snap.tiers.items():
            if not tier.config.enabled:
                continue

            pid_now = discovered.get(tier_id)
            restarted = False

            # ── Restart detection with None-debounce ─────────────────────────
            if pid_now is not None:
                self._tier_none_count[tier_id] = 0
                last = self._tier_last_pid.get(tier_id)
                if last is not None and pid_now != last:
                    # PID changed under us → restart.
                    self._tier_restarts.setdefault(tier_id, []).append(now)
                    self._tier_last_cpu.pop(tier_id, None)  # don't span CPU delta across PIDs
                    restarted = True
                self._tier_last_pid[tier_id] = pid_now
            else:
                self._tier_none_count[tier_id] = self._tier_none_count.get(tier_id, 0) + 1
                if self._tier_none_count[tier_id] >= _NONE_DEBOUNCE:
                    # Confirmed gone — clear baselines so a reappearance counts
                    # as a fresh start (tier came up), not a restart.
                    self._tier_last_pid[tier_id] = None
                    self._tier_last_cpu.pop(tier_id, None)

            # ── Rolling 24h restart window cleanup ───────────────────────────
            cutoff = now - _RESTART_WINDOW
            restarts = [ts for ts in self._tier_restarts.get(tier_id, []) if ts >= cutoff]
            self._tier_restarts[tier_id] = restarts
            restart_count_24h = len(restarts)
            last_restart_ts = restarts[-1] if restarts else None

            if restarted:
                restart_events.append((tier_id, restart_count_24h, pid_now))

            # ── Resource reads ───────────────────────────────────────────────
            rss_mb = 0
            cpu_pct = 0.0
            uptime_sec: Optional[int] = None
            if pid_now is not None:
                rss_mb = _read_rss_mb(pid_now)
                stat = _read_stat(pid_now)
                if stat is not None:
                    total_ticks, starttime_ticks = stat
                    mono = time.monotonic()
                    prev = self._tier_last_cpu.get(tier_id)
                    if prev is not None:
                        prev_ticks, prev_mono = prev
                        dt = mono - prev_mono
                        if dt > 0 and total_ticks >= prev_ticks:
                            cpu_pct = ((total_ticks - prev_ticks) / _CLK_TCK) / dt * 100.0
                    self._tier_last_cpu[tier_id] = (total_ticks, mono)
                    if sys_uptime is not None:
                        uptime_sec = max(0, int(sys_uptime - starttime_ticks / _CLK_TCK))

            observations[tier_id] = {
                "pid": pid_now,
                "rss_mb": rss_mb,
                "cpu_pct": round(cpu_pct, 1),
                "uptime_sec": uptime_sec,
                "restart_count_24h": restart_count_24h,
                "last_restart_ts": last_restart_ts,
                # §10.3 self-offload state — only T1 carries the marker today.
                "offloaded": t1_offloaded if tier_id == "t1" else False,
                "offload_ngl": t1_offload_ngl if tier_id == "t1" else None,
            }

        def update(model):
            for tier_id, obs in observations.items():
                tier = model.tiers.get(tier_id)
                if tier is None:
                    continue
                rt = tier.runtime
                rt.pid = obs["pid"]
                rt.rss_mb = obs["rss_mb"]
                rt.cpu_pct = obs["cpu_pct"]
                rt.uptime_sec = obs["uptime_sec"]
                rt.restart_count_24h = obs["restart_count_24h"]
                rt.last_restart_ts = obs["last_restart_ts"]
                rt.offloaded = obs["offloaded"]
                rt.offload_ngl = obs["offload_ngl"]

        store.apply(update)

        # ── Events (transition-only: only on a freshly-detected restart) ──────
        for tier_id, count, pid in restart_events:
            if count >= _FLAP_THRESHOLD:
                store.emit(
                    type="tier_restart_flapping",
                    severity="warning",
                    tier=tier_id,
                    detail=f"{tier_id} restarting repeatedly: {count} restarts in 24h (pid {pid})",
                    restart_count_24h=count,
                    pid=pid,
                )
                logger.warning("[process] %s flapping: %d restarts/24h", tier_id, count)
            else:
                store.emit(
                    type="tier_restart",
                    severity="info",
                    tier=tier_id,
                    detail=f"{tier_id} process restarted (pid {pid})",
                    restart_count_24h=count,
                    pid=pid,
                )
                logger.info("[process] %s restarted (pid %s, %d/24h)", tier_id, pid, count)
