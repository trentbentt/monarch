"""Derived contract types — the ONLY models this backend declares.

Raw Loki domains (tiers/resources/memory/...) are passed through as dicts;
Loki owns their schema. Here we declare only what the dashboard *derives*:
the status rollups that drive the overview dots and the phone "needs attention"
list. Keeping this surface tiny is deliberate — it cannot drift from
``schema.py`` because it does not duplicate it.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class StatusLevel(str, Enum):
    OK = "ok"          # green
    WARN = "warn"      # amber
    CRIT = "crit"      # red
    UNKNOWN = "unknown"  # grey (source unreachable / absent)

    @property
    def rank(self) -> int:
        return {"ok": 0, "unknown": 1, "warn": 2, "crit": 3}[self.value]


def worst(levels: List["StatusLevel"]) -> "StatusLevel":
    """Roll up child statuses to a parent — the worst wins, but a single
    UNKNOWN never outranks a real WARN/CRIT."""
    if not levels:
        return StatusLevel.UNKNOWN
    return max(levels, key=lambda s: s.rank)


class DomainStatus(BaseModel):
    """One of the 10 infrastructure domains, rolled up to a single light."""
    key: str                       # e.g. "tiers", "memory", "spend"
    label: str                     # human label, e.g. "Engine Room"
    status: StatusLevel
    summary: str                   # one-liner, e.g. "5/6 tiers live"
    counts: dict = Field(default_factory=dict)  # small badge numbers


class Attention(BaseModel):
    """A single thing that is wrong right now — drives the phone column."""
    domain: str
    status: StatusLevel
    message: str


class Overview(BaseModel):
    """Top-level glance object. The phone renders attention[]; the desktop
    renders domains[]; both render `overall`."""
    overall: StatusLevel
    generated_at: Optional[str] = None
    last_updated: Optional[str] = None
    state_age_sec: Optional[float] = None
    stale: bool = False            # state.json older than staleness threshold
    daemon_pid: Optional[int] = None
    domains: List[DomainStatus] = Field(default_factory=list)
    attention: List[Attention] = Field(default_factory=list)


# Threshold past which the state file is considered stale (daemon stalled/down).
STALE_AFTER_SEC = 60.0
