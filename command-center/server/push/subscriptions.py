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


class StoreFull(Exception):
    """The subscription store is at capacity and the endpoint is not already in it."""


def _without_provably_dead(subs: List[dict]) -> List[dict]:
    """Drop stored subscriptions the push service itself disowns (404/410).

    Runs only on the StoreFull path, under the store lock. This is not
    eviction: the property `add` protects is that a subscriber who still
    EXISTS is never displaced, and an endpoint the push service answers
    404/410 for has no subscriber behind it — browsers rotate endpoints, and
    the rotated-away entry can never be delivered to or re-register again.
    Without this, a store full of the operator's own stale rotations refuses
    the operator's live endpoint (M165). Anything other than 404/410 — 2xx,
    5xx, timeout, network down — is NOT proof of death and the entry is kept:
    pruning on silence would rebuild the silencing primitive one layer down,
    with a downed network as the trigger. Probing stops as soon as one slot
    is free, so a registration costs at most a handful of probes."""
    from push import sender  # runtime import: sender imports this module
    live: List[dict] = []
    remaining = list(subs)
    while remaining:
        if len(live) + len(remaining) < config.PUSH_MAX_SUBS:
            live.extend(remaining)  # room already opened; stop probing
            break
        s = remaining.pop(0)
        if sender.probe(s) in (404, 410):
            continue                # the service disowned it: provably dead
        live.append(s)
    return live


def add(subscription: dict) -> int:
    """Upsert by endpoint. Returns the new total count.

    Capacity is enforced by REFUSING a new endpoint, never by evicting a stored
    one. The cap used to keep the most-recent N and drop the oldest, which made
    it a silencing primitive: the operator's own device is the oldest entry
    (registered at PWA install), so anyone able to reach this endpoint could fill
    the store and quietly remove the operator from the delivery list — alerts
    then went only to the newcomers. Refusing instead bounds the store just as
    hard while making a full store loud (the caller gets an error) rather than a
    silent loss of the one subscriber that matters. An endpoint already stored
    always re-registers, so a browser's periodic refresh never trips the cap."""
    ep = subscription.get("endpoint")
    if not ep:
        raise ValueError("subscription missing endpoint")
    with _lock:
        existing = _read()
        kept = [s for s in existing if s.get("endpoint") != ep]
        is_new = len(kept) == len(existing)
        if is_new and len(kept) >= config.PUSH_MAX_SUBS:
            kept = _without_provably_dead(kept)
            if len(kept) >= config.PUSH_MAX_SUBS:
                _write(kept)  # keep any pruning even when still refusing
                raise StoreFull(
                    f"push subscription store is full ({config.PUSH_MAX_SUBS}); "
                    "refusing a new endpoint rather than evicting a stored one")
        kept.append(subscription)
        _write(kept)
        return len(kept)


def remove(endpoint: str) -> None:
    with _lock:
        subs = [s for s in _read() if s.get("endpoint") != endpoint]
        _write(subs)


def all() -> List[dict]:
    with _lock:
        return _read()


def count() -> int:
    return len(all())
