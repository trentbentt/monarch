"""
Shared listener utilities.

Helpers used by more than one listener live here. Promoted out of vram.py
when process.py needed the same port→tier PID attribution (per
master_summary §12.4: "promote from vram.py to loki/listeners/util.py").
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Optional


def run_cmd(cmd: List[str], timeout: float = 3.0, *, strip: bool = False) -> Optional[str]:
    """Run a command; return its stdout on exit 0, else None. A timeout, a
    missing binary (FileNotFoundError) or other OSError is a normal
    'probe unavailable' signal — callers translate None into a note, never an
    error. strip=True trims surrounding whitespace (hardware probes); cron line
    parsing keeps stdout raw."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() if strip else r.stdout


def _port_from_cmdline(pid: int) -> Optional[int]:
    """Parse the --port argument from a process's /proc/{pid}/cmdline.

    Returns the port int if found, else None. Swallows FileNotFoundError /
    PermissionError so a vanished or inaccessible PID is simply "no port".
    """
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        args = cmdline.decode("utf-8", errors="replace").split("\x00")
        for i, arg in enumerate(args):
            if arg in ("--port", "-port") and i + 1 < len(args):
                try:
                    return int(args[i + 1])
                except ValueError:
                    pass
            m = re.match(r"^--port=(\d+)$", arg)
            if m:
                return int(m.group(1))
    except (FileNotFoundError, PermissionError):
        pass
    return None
