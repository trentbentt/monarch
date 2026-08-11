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

from fastapi import Header, HTTPException, Query, Request

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


def _same(supplied: str, expected: str) -> bool:
    """Constant-time compare that DENIES a malformed token instead of raising.

    secrets.compare_digest rejects str with non-ASCII characters (TypeError).
    Uncaught, one non-ASCII byte in the header turned a 401 into a 500 and — far
    worse — skipped _deny(), so that probe left no audit trace at all. Comparing
    the UTF-8 bytes keeps the comparison constant-time and makes every
    well-formed-or-not token take the same denial path."""
    return secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def _valid(authorization: str | None, x_cc_token: str | None) -> bool:
    supplied = _present(authorization, x_cc_token)
    if not supplied:
        return False
    return _same(supplied, get_token())


_REQUEST_DEFAULT_NOTE = """Why the three gates below declare `request: Request = None`.

The annotation is what makes FastAPI inject the live Request; the `= None`
default is for the tests that call these gates DIRECTLY rather than through the
app, and they do so for good reason — a non-ASCII header byte and the SSE
`?token=` branch are paths TestClient cannot produce (test_security.py). A bare
`request: Request` breaks those three security tests; dropping the parameter
gives M171's record nothing to report.

If FastAPI ever stopped injecting, `request` would be None, `params` would fall
back to `{}`, and M171's fix would silently revert to the defect. That is not
left to trust: test_a_denial_records_what_was_attempted asserts method and path
through the real app path, so the fallback cannot pass unnoticed.
"""


def _deny(kind: str, request: "Request | None" = None) -> None:
    """Reject with 401 and leave a trace — token probing must not be silent.

    M171: the trace must identify something. It recorded `params={}` and
    `actor="operator"`, so a probe was indistinguishable from the operator's
    own unpaired client, which is exactly why the 2026-08-04 control_auth
    burst could not be attributed by the session investigating it — the method
    and path had to be recovered from the uvicorn access log instead.

    What is recorded is the method and path ATTEMPTED. Never the supplied
    token: a rejected token is still a secret (it may be the operator's own,
    mistyped) and an audit log is not the place to learn it.
    """
    logger.warning("%s: denied (invalid or missing control token)", kind)
    try:
        from control import audit
        params = {}
        if request is not None:
            params = {"method": request.method, "path": request.url.path}
        audit.record(kind, params, "denied", "invalid or missing control token",
                     actor="unauthenticated")
    except Exception:   # audit must never convert a 401 into a 500
        pass
    raise HTTPException(status_code=401, detail="invalid or missing control token")


async def require_control_token(
    request: Request = None,          # see _REQUEST_DEFAULT_NOTE
    authorization: str | None = Header(default=None),
    x_cc_token: str | None = Header(default=None),
) -> None:
    """FastAPI dependency: 401 unless a valid control token is presented.
    Always enforced (mutations)."""
    if not _valid(authorization, x_cc_token):
        _deny("control_auth", request)


async def require_read_token(
    request: Request = None,
    authorization: str | None = Header(default=None),
    x_cc_token: str | None = Header(default=None),
) -> None:
    """FastAPI dependency for the sensitive READ surface. No-op unless
    CC_REQUIRE_TOKEN_FOR_READS is set, in which case it enforces the same token —
    defense-in-depth over the tailnet trust boundary, operator's choice."""
    if not config.REQUIRE_TOKEN_FOR_READS:
        return
    if not _valid(authorization, x_cc_token):
        _deny("read_auth", request)


async def require_read_token_sse(
    request: Request = None,
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
    if token and _same(token, get_token()):
        return
    _deny("read_auth", request)
