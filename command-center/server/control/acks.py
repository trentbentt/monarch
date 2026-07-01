"""Local event acknowledgement store (no external effect).

Persists acked event_ids so the UI can hide events the operator has handled.
"""
from __future__ import annotations

import json
import threading
from typing import List

import config

_lock = threading.Lock()


def _read() -> List[str]:
    try:
        return json.loads(config.ACK_STORE_PATH.read_text())
    except (OSError, ValueError):
        return []


def ack(event_id: str) -> int:
    with _lock:
        ids = set(_read())
        ids.add(event_id)
        config.ACK_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.ACK_STORE_PATH.write_text(json.dumps(sorted(ids)))
        return len(ids)


def acked() -> List[str]:
    with _lock:
        return _read()
