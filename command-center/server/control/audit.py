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


def record(action: str, params: dict, result: str, detail: str = "",
           dry_run: bool = False, actor: str = "operator") -> None:
    """Append one attempt. `actor` defaults to "operator" because that is true
    of every call site that runs AFTER the token gate — which is all of them
    but one.

    M171: it used to be a hardcoded literal, so the exception was recorded as
    the rule. `control.auth._deny` audits callers who just failed to prove they
    hold the token, and stamped each with the operator's name; a denial in the
    panel was indistinguishable from the operator's own unpaired client. A
    field that asserts a fact it never measured is the M80/M124/M127 class, and
    in a security audit the fabrication is not a wrong number but a wrong
    attribution.
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "params": params,
        "result": result,       # "ok" | "error" | "dry_run" | "denied"
        "detail": detail,
        "dry_run": dry_run,
        "actor": actor,
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


def _entries() -> list:
    """Every parseable entry, chronological. The log is size-capped by
    _rotate_if_needed, so reading it whole is bounded."""
    try:
        lines = config.AUDIT_LOG.read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def tail(n: int = 50, exclude: frozenset | set | None = None) -> list:
    """Last n entries, chronological.

    `exclude` drops entries by action BEFORE taking the last n — the difference
    matters. Slicing the raw last-n lines and filtering afterwards still lets a
    high-volume action starve the view: when the read-gate armed, an unpaired
    client wrote ~26 `read_auth` denials/min and the operator's last-15 window
    held 15 denials and zero control actions. Filtering first means the view
    shows the last n of what it is *for*.

    The denials are not dropped from the LOG — they are the token-probing trail
    — only from a view whose job is something else. `count_action` keeps the
    suppressed volume visible.
    """
    entries = _entries()
    if exclude:
        entries = [e for e in entries if e.get("action") not in exclude]
    return entries[-n:] if n >= 0 else entries


def count_action(action: str) -> int:
    """How many entries of one action are in the log — so a view that suppresses
    a flood can still report that the flood is happening."""
    return sum(1 for e in _entries() if e.get("action") == action)
