"""Append-only audit log for every control attempt.

One JSON object per line. Never raises into the request path — an audit failure
must not block (or silently allow) an action without a trace, so failures are
swallowed after a best-effort stderr note.
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone

import config

_lock = threading.Lock()


def record(action: str, params: dict, result: str, detail: str = "", dry_run: bool = False) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "params": params,
        "result": result,       # "ok" | "error" | "dry_run" | "denied"
        "detail": detail,
        "dry_run": dry_run,
        "actor": "operator",
    }
    line = json.dumps(entry)
    try:
        with _lock:
            config.AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed()
            with open(config.AUDIT_LOG, "a") as f:
                f.write(line + "\n")
    except OSError as e:
        print(f"[audit] failed to write: {e}", file=sys.stderr)


def _rotate_if_needed() -> None:
    """Size-cap the append-only log so an unauthenticated denied-attempt flood
    can't exhaust disk. Past AUDIT_LOG_MAX_BYTES, move the current log to a single
    .1 backup (replacing any prior backup) so disk stays bounded at ~2x the cap.
    Caller holds _lock."""
    try:
        if config.AUDIT_LOG.exists() and config.AUDIT_LOG.stat().st_size >= config.AUDIT_LOG_MAX_BYTES:
            config.AUDIT_LOG.replace(config.AUDIT_LOG.with_suffix(config.AUDIT_LOG.suffix + ".1"))
    except OSError as e:
        print(f"[audit] rotate failed: {e}", file=sys.stderr)


def tail(n: int = 50) -> list:
    try:
        lines = config.AUDIT_LOG.read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out
