"""Event → Web Push bridge.

Watches state.json events and pushes the ones that matter, honoring the
overnight-window quieting doctrine (§9.5.3):
  - interrupt classes (thermal / security / spend-burst / RAM) ALWAYS push,
    bypassing the window;
  - other critical events push only OUTSIDE the overnight window.

The decision (`should_notify`) is pure and unit-tested; delivery is separate.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, time as dtime
from typing import Optional

import config
from push import sender


def _parse_hhmm(s: Optional[str]) -> Optional[dtime]:
    if not s:
        return None
    try:
        h, m = s.split(":")[:2]
        return dtime(int(h), int(m))
    except (ValueError, TypeError):
        return None


def in_overnight_window(prefs: dict, now_local: datetime) -> bool:
    start = _parse_hhmm((prefs or {}).get("overnight_window_start"))
    end = _parse_hhmm((prefs or {}).get("overnight_window_end"))
    if not start or not end:
        return False
    t = now_local.time()
    if start <= end:
        return start <= t < end
    # wraps midnight (e.g. 23:00 -> 07:00)
    return t >= start or t < end


def should_notify(event: dict, prefs: dict, now_local: datetime) -> bool:
    etype = (event or {}).get("type", "")
    sev = (event or {}).get("severity", "").lower()
    is_interrupt = etype in config.PUSH_INTERRUPT_TYPES
    if is_interrupt:
        return True                              # bypasses quieting
    if in_overnight_window(prefs, now_local):
        return False                             # quieted
    return sev in ("critical", "crit", "error")


def build_payload(event: dict) -> dict:
    etype = event.get("type", "event")
    sev = event.get("severity", "info")
    return {
        "title": f"Monarch · {etype}",
        "body": event.get("detail") or f"{sev} event on {event.get('tier', 'system')}",
        "severity": sev,
        "event_id": event.get("event_id"),
        "tag": etype,
        "timestamp": event.get("timestamp"),
    }


def should_notify_ask(ask: dict, prefs: dict, now_local: datetime) -> bool:
    """Blocking asks page the operator (something is waiting on them).
    Non-blocking asks auto-proceed — their surface is the in-app countdown.
    Asks are never interrupt-class: the overnight window quiets them (§9.5.3)."""
    if not (ask or {}).get("blocking", True):
        return False
    return not in_overnight_window(prefs, now_local)


def build_ask_payload(ask: dict) -> dict:
    aid = (ask or {}).get("action_id", "action")
    return {
        "title": f"Monarch · ask: {aid}",
        "body": ask.get("rationale") or "approval requested",
        "severity": "ask",
        "event_id": f"ask-{aid}-{ask.get('proposed_at')}",
        "tag": f"ask-{aid}",
        "timestamp": ask.get("proposed_at"),
    }


def _ask_key(ask: dict) -> tuple:
    return (ask.get("action_id"), str(ask.get("proposed_at")))


class PushBridge:
    """Subscribes to the state watcher, dispatches push for new qualifying events."""

    def __init__(self, watcher):
        self._watcher = watcher
        self._seen: set = set()
        self._seen_asks: set = set()
        self._task: Optional[asyncio.Task] = None
        self._primed = False

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        sub = self._watcher.subscribe()
        try:
            async for state in sub:
                self._handle(state)
        except asyncio.CancelledError:
            await sub.aclose()
            raise

    def _handle(self, state: dict) -> None:
        events = ((state.get("events") or {}).get("log")) or []
        asks = ((state.get("decisions") or {}).get("pending_asks")) or []
        prefs = (state.get("operator") or {}).get("preferences") or {}
        now = datetime.now()
        new_events = [e for e in events if e.get("event_id") not in self._seen]
        new_asks = [a for a in asks if _ask_key(a) not in self._seen_asks]
        for e in events:
            self._seen.add(e.get("event_id"))
        for a in asks:
            self._seen_asks.add(_ask_key(a))
        if not self._primed:
            # First snapshot: record history, push nothing (no restart replay).
            self._primed = True
            return
        for e in new_events:
            if should_notify(e, prefs, now):
                try:
                    sender.send_all(build_payload(e))
                except Exception:
                    pass  # never let a delivery error kill the bridge
        for a in new_asks:
            if should_notify_ask(a, prefs, now):
                try:
                    sender.send_all(build_ask_payload(a))
                except Exception:
                    pass
