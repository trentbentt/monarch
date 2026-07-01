"""Operator control-token auth.

Reads/creates a single operator token. Control endpoints require it via
``Authorization: Bearer <token>`` or ``X-CC-Token: <token>``. Comparison is
constant-time. Mutations are always gated; the sensitive read surface is gated
too when CC_REQUIRE_TOKEN_FOR_READS is set. Denied attempts are audited so
token-probing leaves a trace.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import Header, HTTPException, Query

import config

logger = logging.getLogger(__name__)

_token: str | None = None


def get_token() -> str:
    """Resolve the control token: env override, else a persisted generated one."""
    global _token
    if _token is not None:
        return _token
    if config.CONTROL_TOKEN:
        _token = config.CONTROL_TOKEN
        return _token
    path = config.CONTROL_TOKEN_PATH
    if path.exists():
        _token = path.read_text().strip()
        if _token:
            return _token
    _token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_token)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return _token


def reset_cache() -> None:
    """Test hook: forget the cached token so config overrides re-resolve."""
    global _token
    _token = None


def _present(authorization: str | None, x_cc_token: str | None) -> str | None:
    if x_cc_token:
        return x_cc_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return None


def _valid(authorization: str | None, x_cc_token: str | None) -> bool:
    supplied = _present(authorization, x_cc_token)
    if not supplied:
        return False
    return secrets.compare_digest(supplied, get_token())


def _deny(kind: str) -> None:
    """Reject with 401 and leave a trace — token probing must not be silent."""
    logger.warning("%s: denied (invalid or missing control token)", kind)
    try:
        from control import audit
        audit.record(kind, {}, "denied", "invalid or missing control token")
    except Exception:   # audit must never convert a 401 into a 500
        pass
    raise HTTPException(status_code=401, detail="invalid or missing control token")


async def require_control_token(
    authorization: str | None = Header(default=None),
    x_cc_token: str | None = Header(default=None),
) -> None:
    """FastAPI dependency: 401 unless a valid control token is presented.
    Always enforced (mutations)."""
    if not _valid(authorization, x_cc_token):
        _deny("control_auth")


async def require_read_token(
    authorization: str | None = Header(default=None),
    x_cc_token: str | None = Header(default=None),
) -> None:
    """FastAPI dependency for the sensitive READ surface. No-op unless
    CC_REQUIRE_TOKEN_FOR_READS is set, in which case it enforces the same token —
    defense-in-depth over the tailnet trust boundary, operator's choice."""
    if not config.REQUIRE_TOKEN_FOR_READS:
        return
    if not _valid(authorization, x_cc_token):
        _deny("read_auth")


async def require_read_token_sse(
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    x_cc_token: str | None = Header(default=None),
) -> None:
    """Read-gate for the SSE stream. EventSource cannot set request headers, so
    this ALSO accepts the token as a ``?token=`` query param — otherwise the
    /stream channel (which ships the same full payload as the gated /state) would
    be ungateable, silently defeating the read-gate (review H7). No-op unless
    CC_REQUIRE_TOKEN_FOR_READS. Header paths stay primary; the query form is
    SSE-only (URLs can be logged) and used only when the gate is enabled."""
    if not config.REQUIRE_TOKEN_FOR_READS:
        return
    if _valid(authorization, x_cc_token):
        return
    if token and secrets.compare_digest(token, get_token()):
        return
    _deny("read_auth")
