"""Phase 2 legibility: make Loki's decisions and routing readable.

Pure functions over the raw state dict (no I/O) — same defensive style as
derive.py. Two surfaces:
  - derive_routing(state):  router/gate/dispatcher health + active LoRA + which
                            tiers served recent traffic.
  - enrich_pending(state):  pending operator asks joined to the N=12 ledger so
                            the UI can show the action, *why* (rationale), its
                            trust state, and a live veto countdown.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from derive import _interp, _components_by_name  # reuse status mapping
from models import StatusLevel, worst

_ROUTING_NAMES = ["litellm", "validation-gate", "lora-dispatcher"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
    except (ValueError, TypeError):
        return None


def derive_routing(state: dict) -> dict:
    comps = _components_by_name(state)
    components = []
    levels = []
    for name in _ROUTING_NAMES:
        c = comps.get(name) or {}
        lvl = _interp(c.get("status")) if c else StatusLevel.UNKNOWN
        levels.append(lvl)
        components.append({
            "name": name,
            "status": lvl.value,
            "raw_status": c.get("status"),
            "port": c.get("port"),
            "response_ms": c.get("response_ms"),
            "last_seen_healthy": c.get("last_seen_healthy"),
        })

    # Active LoRA + recent traffic, per tier (config.active_lora + performance).
    tiers = state.get("tiers") or {}
    loras = []
    traffic = []
    for tid, t in sorted(tiers.items()):
        cfg = t.get("config") or {}
        perf = t.get("performance") or {}
        lora = cfg.get("active_lora")
        if lora:
            loras.append({"tier": tid, "lora": lora})
        completions = perf.get("completions_in_window") or 0
        errors = perf.get("errors_in_window") or 0
        if completions or errors:
            traffic.append({"tier": tid, "completions": completions, "errors": errors})

    return {
        "status": worst(levels).value,
        "components": components,
        "active_loras": loras,
        "recent_traffic": sorted(traffic, key=lambda x: x["completions"], reverse=True),
    }


def enrich_pending(state: dict) -> List[dict]:
    """Join decisions.pending_asks to the ledger; add live veto countdown."""
    dec = state.get("decisions") or {}
    ledger = {l.get("action_id"): l for l in (dec.get("ledger") or [])}
    now = _now()
    out = []
    for ask in dec.get("pending_asks") or []:
        action_id = ask.get("action_id")
        led = ledger.get(action_id, {})
        blocking = ask.get("blocking", True)
        expires_at = ask.get("expires_at")
        secs_left = None
        if not blocking and expires_at:
            exp = _parse_ts(expires_at)
            if exp:
                secs_left = max(0.0, (exp - now).total_seconds())
        out.append({
            "action_id": action_id,
            "rationale": ask.get("rationale"),          # the WHY
            "tier": ask.get("tier"),
            "kind": ask.get("kind"),
            "blocking": blocking,
            "proposed_at": ask.get("proposed_at"),
            "expires_at": expires_at,
            "veto_seconds_remaining": secs_left,         # frontend recomputes live
            "params": ask.get("params") or {},
            # ledger enrichment (trust legibility)
            "description": led.get("description"),
            "ledger_state": led.get("state"),
            "current_tier": led.get("current_tier"),
            "target_tier": led.get("target_tier"),
            "clean_run_count": led.get("clean_run_count"),
            "total_runs": led.get("total_runs"),
            "last_outcome": led.get("last_outcome"),
        })
    # Non-blocking veto windows first (time-critical), then by proposed_at.
    out.sort(key=lambda a: (a["veto_seconds_remaining"] is None,
                            a["veto_seconds_remaining"] if a["veto_seconds_remaining"] is not None else 0))
    return out
