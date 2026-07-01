"""Thin wrappers over the loki-q CLI.

For Phase 1 the state.json watcher covers the data we need; loki-q is a
secondary surface for rendered detail (e.g. ``events N``). All calls are
read-only, time-boxed, and degrade to None on any failure.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import config

# Allow-list of read-only subcommands. NEVER pass user input as a subcommand.
_READ_ONLY = {
    "vram", "health", "tiers", "workloads", "quotas", "schedule", "memory",
    "decisions", "events", "all", "json", "skill-drafts", "curated-gc",
    "evercore", "profile-drift",
}


async def run(subcommand: str, arg: Optional[str] = None, timeout: float = 5.0) -> Optional[str]:
    """Run ``loki-q <subcommand> [arg]`` and return stdout, or None on failure.

    Only allow-listed read-only subcommands are permitted.
    """
    if subcommand not in _READ_ONLY:
        raise ValueError(f"loki-q subcommand not allow-listed: {subcommand!r}")
    cmd = [config.LOKIQ_BIN, subcommand]
    if arg is not None:
        # arg is only ever a numeric count for `events N`; coerce to str, no shell.
        cmd.append(str(arg))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return out.decode("utf-8", errors="replace")
