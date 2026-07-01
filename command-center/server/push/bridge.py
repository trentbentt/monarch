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


class PushBridge:
    """Subscribes to the state watcher, dispatches push for new qualifying events."""

    def __init__(self, watcher):
        self._watcher = watcher
        self._seen: set = set()
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
        prefs = (state.get("operator") or {}).get("preferences") or {}
        now = datetime.now()
        new = [e for e in events if e.get("event_id") not in self._seen]
        for e in events:
            self._seen.add(e.get("event_id"))
        if not self._primed:
            # First snapshot: record seen events but don't replay history as push.
            self._primed = True
            return
        for e in new:
            if should_notify(e, prefs, now):
                try:
                    sender.send_all(build_payload(e))
                except Exception:
                    pass  # never let a delivery error kill the bridge
