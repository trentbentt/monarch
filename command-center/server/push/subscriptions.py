"""Persisted Web Push subscription store (JSON file, keyed by endpoint)."""
from __future__ import annotations

import json
import threading
from typing import List

import config

_lock = threading.Lock()


def _read() -> List[dict]:
    p = config.PUSH_SUBS_PATH
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return []


def _write(subs: List[dict]) -> None:
    p = config.PUSH_SUBS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(subs, indent=2))


def add(subscription: dict) -> int:
    """Upsert by endpoint. Returns the new total count."""
    ep = subscription.get("endpoint")
    if not ep:
        raise ValueError("subscription missing endpoint")
    with _lock:
        subs = [s for s in _read() if s.get("endpoint") != ep]
        subs.append(subscription)
        # Registration is unauthenticated — cap the store so a tailnet peer can't
        # grow it without bound. Keep the most-recent N (FIFO drop of the oldest).
        if len(subs) > config.PUSH_MAX_SUBS:
            subs = subs[-config.PUSH_MAX_SUBS:]
        _write(subs)
        return len(subs)


def remove(endpoint: str) -> None:
    with _lock:
        subs = [s for s in _read() if s.get("endpoint") != endpoint]
        _write(subs)


def all() -> List[dict]:
    with _lock:
        return _read()


def count() -> int:
    return len(all())
