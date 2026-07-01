"""Roll raw Loki state.json into the derived Overview.

Every deriver is defensive: a missing/renamed key degrades that domain to
UNKNOWN (grey) rather than raising, so one schema drift never blanks the whole
dashboard. This is the single place that encodes "what does "OK" mean" for each
of the 10 domains.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from models import (
    Attention,
    DomainStatus,
    Overview,
    StatusLevel,
    STALE_AFTER_SEC,
    worst,
)

_OK = StatusLevel.OK
_WARN = StatusLevel.WARN
_CRIT = StatusLevel.CRIT
_UNK = StatusLevel.UNKNOWN


def _interp(status: Optional[str]) -> StatusLevel:
    """Map a free-text health string to a level."""
    if not status:
        return _UNK
    s = status.lower()
    if any(k in s for k in ("healthy", "live", "ok", "up", "ready", "running")):
        return _OK
    if any(k in s for k in ("idle", "degraded", "soft", "warn", "elevated", "stale")):
        return _WARN
    if any(k in s for k in ("unhealthy", "unresponsive", "down", "dead", "imminent", "error", "crit")):
        return _CRIT
    return _UNK


def _age_sec(ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except (ValueError, TypeError):
        return None


# --- per-domain derivers -----------------------------------------------------

def _tiers(state: dict, att: list) -> DomainStatus:
    tiers = state.get("tiers") or {}
    levels, live, total = [], 0, 0
    for tid, t in tiers.items():
        cfg = t.get("config") or {}
        rt = t.get("runtime") or {}
        if not cfg.get("enabled", True):
            continue
        total += 1
        st = (rt.get("state") or "").lower()
        burst = cfg.get("burst_only", False)
        if st in ("live", "running"):
            live += 1
            lvl = _OK
        elif st in ("idle", "soft_offload") and burst:
            lvl = _OK            # expected for burst-only tiers
        elif st in ("idle", "soft_offload"):
            lvl = _WARN
            att.append(Attention(domain="tiers", status=_WARN,
                                 message=f"{tid.upper()} offloaded ({st})"))
        elif st in ("unresponsive", "down", "error"):
            lvl = _CRIT
            att.append(Attention(domain="tiers", status=_CRIT,
                                 message=f"{tid.upper()} {st}"))
        else:
            lvl = _interp(rt.get("health_status"))
        levels.append(lvl)
    return DomainStatus(key="tiers", label="Engine Room", status=worst(levels),
                        summary=f"{live}/{total} tiers live", counts={"live": live, "total": total})


def _vitals(state: dict, att: list) -> DomainStatus:
    res = state.get("resources") or {}
    vram = res.get("vram") or {}
    oom = (vram.get("oom_risk") or "").lower()
    lvl = _OK
    if oom in ("imminent",):
        lvl = _CRIT
        att.append(Attention(domain="vitals", status=_CRIT, message="VRAM OOM imminent"))
    elif oom in ("elevated",):
        lvl = _WARN
        att.append(Attention(domain="vitals", status=_WARN, message="VRAM pressure elevated"))
    elif not oom:
        lvl = _UNK
    used = vram.get("used_mb")
    total = vram.get("total_mb")
    pct = round(100 * used / total) if used and total else None
    summary = f"VRAM {pct}%" if pct is not None else "VRAM —"
    return DomainStatus(key="vitals", label="Vitals", status=lvl, summary=summary,
                        counts={"vram_used_mb": used or 0, "vram_total_mb": total or 0,
                                "vram_pct": pct or 0, "oom_risk": oom or "unknown"})


_ROUTING_COMPONENTS = {"litellm", "validation-gate", "lora-dispatcher"}


def _components_by_name(state: dict) -> dict:
    health = state.get("health") or {}
    out = {}
    for c in health.get("components") or []:
        out[c.get("name", "")] = c
    return out


def _routing(state: dict, att: list) -> DomainStatus:
    comps = _components_by_name(state)
    levels = []
    for name in _ROUTING_COMPONENTS:
        c = comps.get(name)
        lvl = _interp(c.get("status")) if c else _UNK
        if lvl is _CRIT:
            att.append(Attention(domain="routing", status=_CRIT, message=f"{name} down"))
        levels.append(lvl)
    return DomainStatus(key="routing", label="Request Routing", status=worst(levels),
                        summary="routes requests to tiers",
                        counts={"checked": len(_ROUTING_COMPONENTS)})


def _memory(state: dict, att: list) -> DomainStatus:
    mem = state.get("memory") or {}
    layers = mem.get("layers") or {}
    levels = []
    unhealthy = 0
    for lname, l in layers.items():
        lvl = _interp(l.get("health") or l.get("health_signal"))
        if lvl in (_CRIT, _WARN) and lvl is _CRIT:
            unhealthy += 1
            att.append(Attention(domain="memory", status=_CRIT,
                                 message=f"Memory {lname} ({l.get('name', '')}) unhealthy"))
        levels.append(lvl)
    gc_stale = len(mem.get("gc_proposals_stale") or [])
    sd_stale = len(mem.get("skill_drafts_stale") or [])
    if gc_stale or sd_stale:
        levels.append(_WARN)
        att.append(Attention(domain="memory", status=_WARN,
                             message=f"{gc_stale} stale GC, {sd_stale} stale skill-drafts"))
    return DomainStatus(key="memory", label="Memory Map", status=worst(levels),
                        summary=f"{len(layers)} layers, {unhealthy} unhealthy",
                        counts={"layers": len(layers), "unhealthy": unhealthy,
                                "gc_total": mem.get("gc_proposals_total", 0),
                                "skill_drafts_total": mem.get("skill_drafts_total", 0)})


def _workflows(state: dict, att: list) -> DomainStatus:
    comps = _components_by_name(state)
    c = comps.get("n8n")
    lvl = _interp(c.get("status")) if c else _UNK
    if lvl is _CRIT:
        att.append(Attention(domain="workflows", status=_CRIT, message="n8n down"))
    return DomainStatus(key="workflows", label="Workflows", status=lvl,
                        summary="n8n orchestration", counts={})


def _schedule(state: dict, att: list) -> DomainStatus:
    sched = state.get("schedule") or {}
    missed = len(sched.get("missed_runs_24h") or [])
    collisions = len(sched.get("collisions") or [])
    stale = len(sched.get("stale_entries") or [])
    lvl = _OK
    if missed or stale:
        lvl = _WARN
        att.append(Attention(domain="schedule", status=_WARN,
                             message=f"{missed} missed runs, {stale} stale cron entries"))
    if collisions:
        lvl = worst([lvl, _WARN])
        att.append(Attention(domain="schedule", status=_WARN,
                             message=f"{collisions} cron collisions upcoming"))
    upcoming = len(sched.get("upcoming_60min") or [])
    return DomainStatus(key="schedule", label="Schedule", status=lvl,
                        summary=f"{upcoming} in next 60m",
                        counts={"upcoming_60min": upcoming, "missed_24h": missed,
                                "collisions": collisions, "stale": stale})


def _authority(state: dict, att: list) -> DomainStatus:
    dec = state.get("decisions") or {}
    pending = dec.get("pending_asks") or []
    lvl = _OK
    if pending:
        lvl = _WARN
        att.append(Attention(domain="authority", status=_WARN,
                             message=f"{len(pending)} pending operator ask(s)"))
    return DomainStatus(key="authority", label="Authority", status=lvl,
                        summary=f"{len(pending)} pending asks",
                        counts={"pending_asks": len(pending),
                                "ledger": len(dec.get("ledger") or [])})


_SEV_LEVEL = {"critical": _CRIT, "crit": _CRIT, "error": _CRIT,
              "warning": _WARN, "warn": _WARN, "info": _OK, "debug": _OK}


def _events(state: dict, att: list) -> DomainStatus:
    ev = state.get("events") or {}
    log = ev.get("log") or []
    levels = [_SEV_LEVEL.get((e.get("severity") or "").lower(), _UNK) for e in log[-20:]]
    crit = sum(1 for l in levels if l is _CRIT)
    return DomainStatus(key="events", label="Events", status=worst(levels) if levels else _OK,
                        summary=f"{len(log)} recent, {crit} critical",
                        counts={"recent": len(log), "critical": crit})


_PLACEHOLDER_QUOTA = re.compile(r"^pro_\d+$")


def _spend(state: dict, att: list) -> DomainStatus:
    # Drop unconfigured placeholder slots (pro_1..pro_N — no provider/budget
    # recorded) so the count agrees with the Spend card, which hides them.
    q = {k: v for k, v in ((state.get("quotas") or {}).get("quotas") or {}).items()
         if not _PLACEHOLDER_QUOTA.match(k)}
    levels = []
    for name, row in q.items():
        st = (row.get("status") or "").lower()
        used_pct = row.get("used_pct")
        crit_t = row.get("threshold_critical_pct")
        warn_t = row.get("threshold_warning_pct")
        lvl = _OK
        if st in ("over", "exhausted", "critical"):
            lvl = _CRIT
        elif st in ("warning", "warn"):
            lvl = _WARN
        elif used_pct is not None and crit_t is not None and used_pct >= crit_t:
            lvl = _CRIT
        elif used_pct is not None and warn_t is not None and used_pct >= warn_t:
            lvl = _WARN
        if lvl is _CRIT:
            att.append(Attention(domain="spend", status=_CRIT,
                                 message=f"{row.get('name', name)} budget critical"))
        levels.append(lvl)
    return DomainStatus(key="spend", label="Spend", status=worst(levels) if levels else _UNK,
                        summary=f"{len(q)} providers tracked", counts={"providers": len(q)})


def _docs(state: dict, att: list) -> DomainStatus:
    # Documentation router has no live health signal; it's a query surface.
    # Always available when the backend is up. Phase 2 wires the search.
    return DomainStatus(key="docs", label="Docs Router", status=_OK,
                        summary="doc lookup ready", counts={})


_DERIVERS = [_tiers, _vitals, _routing, _memory, _workflows,
             _schedule, _authority, _events, _spend, _docs]


def derive_overview(state: dict) -> Overview:
    """Top-level entry: raw state.json dict -> Overview with all 10 domains."""
    att: list = []
    domains = [d(state, att) for d in _DERIVERS]
    last_updated = state.get("last_updated")
    age = _age_sec(last_updated)
    stale = age is not None and age > STALE_AFTER_SEC
    # Overall rolls up domains; a stale spine forces at least WARN.
    overall = worst([d.status for d in domains])
    if stale:
        overall = worst([overall, _WARN])
        att.insert(0, Attention(domain="daemon", status=_WARN,
                                message=f"state.json stale ({int(age)}s old) — daemon may be stalled"))
    # Attention sorted worst-first for the phone column.
    att.sort(key=lambda a: a.status.rank, reverse=True)
    return Overview(
        overall=overall,
        generated_at=datetime.now(timezone.utc).isoformat(),
        last_updated=last_updated,
        state_age_sec=age,
        stale=stale,
        daemon_pid=state.get("daemon_pid"),
        domains=domains,
        attention=att,
    )
