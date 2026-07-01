"""StateWatcher — the spine.

Polls ``state.json`` mtime and holds the latest parsed dict in memory. Exposes:
  - ``current()``            latest parsed state (or {} if never read)
  - ``snapshot()``           (state, mtime, read_ok)
  - ``subscribe()``          async iterator yielding the state on every change

Parsing is resilient: a mid-write torn read (JSONDecodeError) keeps the previous
good snapshot rather than blanking the dashboard.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import AsyncIterator, Optional, Tuple

import config


class StateWatcher:
    def __init__(self, path: Optional[Path] = None, poll_sec: Optional[float] = None):
        self._path = Path(path or config.STATE_PATH)
        self._poll = poll_sec if poll_sec is not None else config.STATE_POLL_SEC
        self._state: dict = {}
        self._mtime: float = 0.0
        self._read_ok: bool = False
        self._version: int = 0           # bumps on every accepted change
        self._cond = asyncio.Condition()
        self._task: Optional[asyncio.Task] = None

    # --- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        await self._read_once()          # prime synchronously before serving
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # --- reads ---------------------------------------------------------------
    def current(self) -> dict:
        return self._state

    def snapshot(self) -> Tuple[dict, float, bool]:
        return self._state, self._mtime, self._read_ok

    async def subscribe(self) -> AsyncIterator[dict]:
        """Yield the latest state immediately, then again on every change."""
        last_seen = -1
        while True:
            async with self._cond:
                if self._version == last_seen:
                    await self._cond.wait()
                last_seen = self._version
                state = self._state
            yield state

    # --- internals -----------------------------------------------------------
    async def _read_once(self) -> bool:
        try:
            st = self._path.stat()
        except OSError:
            return False
        if st.st_mtime == self._mtime and self._read_ok:
            return False                 # unchanged
        try:
            data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return False                 # torn/locked read — keep prior snapshot
        async with self._cond:
            self._state = data
            self._mtime = st.st_mtime
            self._read_ok = True
            self._version += 1
            self._cond.notify_all()
        return True

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll)
            try:
                await self._read_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never let the watcher die on an unexpected error.
                await asyncio.sleep(self._poll)
