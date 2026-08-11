"""Security-surface regression tests (review HIGH/MEDIUM findings).

Closes the gaps test_api.py left open:
- the REAL actuation path (token -> confirm-gate -> execute -> audit), not just
  the forced-dry-run path (test_api hardcodes CC_CONTROL_DRY_RUN=1);
- denied control-token attempts are audited (token-probing leaves a trace);
- the Authorization: Bearer branch (test_api only covers X-CC-Token);
- the CC_REQUIRE_TOKEN_FOR_READS read-gate (sensitive reads 401 without the
  token, 200 with) — defense-in-depth over the tailnet trust boundary.

Uses monkeypatch.setenv so the read-gate flag auto-restores and can never bleed
into the other suites' open-read assumptions.
"""
import importlib
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

FIXTURE = Path(__file__).parent / "fixtures" / "state.sample.json"
TOK = {"X-CC-Token": "test-token-123"}


def _make_app(tmp_path, monkeypatch, *, dry_run="1", require_reads="0"):
    env = {
        "CC_STATE_PATH": str(FIXTURE),
        "CC_RUNTIME_DIR": str(tmp_path / "runtime"),
        "CC_PUSH_KEYS_PATH": str(tmp_path / "vapid.json"),
        "CC_PUSH_SUBS_PATH": str(tmp_path / "subs.json"),
        "CC_SKILL_DRAFTS_DIR": str(tmp_path / "skill-drafts"),
        "CC_GC_PROPOSALS_DIR": str(tmp_path / "gc-proposals"),
        "CC_VAULT_DIR": str(tmp_path / "vault"),
        "CC_CONTROL_TOKEN": "test-token-123",
        "CC_CONTROL_DRY_RUN": dry_run,
        "CC_REQUIRE_TOKEN_FOR_READS": require_reads,
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    (tmp_path / "vault").mkdir(exist_ok=True)
    (tmp_path / "vault" / "doc.md").write_text("# Doc\n## Routing\nLiteLLM router.\n")
    import config
    importlib.reload(config)
    import push.vapid as _v
    _v._priv = None
    import docs_router as _d
    _d._index_sig = None
    import control.auth as _a
    _a.reset_cache()
    import main
    importlib.reload(main)
    return main


def _audit_text(tmp_path):
    log = tmp_path / "runtime" / "control.audit.log"
    return log.read_text() if log.exists() else ""


def test_security_headers_present_on_every_response(tmp_path, monkeypatch):
    """The served PWA (and the API) must carry a CSP + the standard hardening
    headers. The PWA shipped with none, so any script-injection vector on its
    origin could read the operator token and drive the control plane (review H7).
    Mirrors the strict CSP the Tauri desktop app already pins."""
    main = _make_app(tmp_path, monkeypatch)
    with TestClient(main.app) as c:
        r = c.get("/api/overview")
    assert r.status_code == 200, r.text
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "no-referrer"


def test_real_actuation_path_executes_and_audits(tmp_path, monkeypatch):
    """dry-run OFF: a confirmed action must traverse the full route — token
    check -> confirm gate -> real execute -> audit. subprocess is mocked so no
    real actuator fires, but the wiring test_api never exercises is covered."""
    main = _make_app(tmp_path, monkeypatch, dry_run="0")
    import control.registry as registry

    calls = {}

    def fake_run(argv, **kw):
        calls["argv"] = argv
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(registry.subprocess, "run", fake_run)

    with TestClient(main.app) as c:
        r = c.post(
            "/api/control/veto",
            json={"confirm": True, "params": {"action_id": "offload_t1_reasoning"}},
            headers=TOK,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("dry_run") is not True       # real path, not a preview
    assert body["ok"] is True
    assert "argv" in calls, "real execute path never reached subprocess"
    assert calls["argv"][0] == registry.config.LOKIQ_BIN
    assert "veto" in calls["argv"] and "offload_t1_reasoning" in calls["argv"]
    assert "veto" in _audit_text(tmp_path)        # the real run was audited


def test_denied_control_token_is_audited(tmp_path, monkeypatch):
    main = _make_app(tmp_path, monkeypatch)
    with TestClient(main.app) as c:
        r = c.post("/api/control/t1_restore", json={"confirm": True},
                   headers={"X-CC-Token": "wrong"})
    assert r.status_code == 401
    assert "denied" in _audit_text(tmp_path), "token-probing left no audit trace"


def test_bearer_token_branch(tmp_path, monkeypatch):
    main = _make_app(tmp_path, monkeypatch)
    with TestClient(main.app) as c:
        ok = c.get("/api/control/verify", headers={"Authorization": "Bearer test-token-123"})
        bad = c.get("/api/control/verify", headers={"Authorization": "Bearer nope"})
    assert ok.status_code == 200
    assert bad.status_code == 401


def test_read_gate_off_by_default(tmp_path, monkeypatch):
    main = _make_app(tmp_path, monkeypatch)   # require_reads default "0"
    with TestClient(main.app) as c:
        assert c.get("/api/state").status_code == 200


def test_read_gate_on_requires_token(tmp_path, monkeypatch):
    main = _make_app(tmp_path, monkeypatch, require_reads="1")
    with TestClient(main.app) as c:
        # /overview ships the full derived state, so it is now gated like /state
        # (previously open, which silently defeated the gate — review H7).
        assert c.get("/api/overview").status_code == 401
        assert c.get("/api/overview", headers=TOK).status_code == 200
        assert c.get("/api/state").status_code == 401             # full dump gated
        assert c.get("/api/state", headers=TOK).status_code == 200
        assert c.get("/api/memory/vault/tree").status_code == 401  # doctrine gated
        assert c.get("/api/memory/vault/tree", headers=TOK).status_code == 200


def test_read_gate_covers_all_state_and_content_reads(tmp_path, monkeypatch):
    """Every full-state / content read is now gated, not just /state — closing the
    holes where /overview, /routing, /pending, /memory/queues and /docs/search
    streamed sensitive data with the gate on (review H7)."""
    main = _make_app(tmp_path, monkeypatch, require_reads="1")
    gated = ["/api/overview", "/api/routing", "/api/pending",
             "/api/memory/queues", "/api/docs/search"]
    with TestClient(main.app) as c:
        for path in gated:
            assert c.get(path).status_code == 401, f"{path} is not gated"
            assert c.get(path, headers=TOK).status_code == 200, f"{path} rejects a valid token"


def test_read_gate_covers_the_whole_codebase_surface(tmp_path, monkeypatch):
    """Both /api/codebase/* routes are gated. `projects` shipped without the
    dependency its sibling carries, so with the gate ON it still returned every
    indexed repo's name and absolute root_path to an untokened caller — an
    inconsistency inside one feature block, not a deliberate open surface."""
    main = _make_app(tmp_path, monkeypatch, require_reads="1")
    with TestClient(main.app) as c:
        assert c.get("/api/codebase/projects").status_code == 401
        assert c.get("/api/codebase/projects", headers=TOK).status_code == 200
        # sibling, asserted alongside so the block can't drift apart again
        assert c.get("/api/codebase/search?project=p&q=x").status_code == 401


def test_sse_stream_gated_and_accepts_query_token(tmp_path, monkeypatch):
    """The SSE /stream ships the same payload as the gated /state, so it must be
    gated too. EventSource can't send headers, so the gate also accepts ?token=
    (review H7). Endpoint-level: no token → 401 (the dependency rejects before any
    streaming). The accept path is unit-tested on the dependency to avoid hanging
    on the infinite SSE generator."""
    import asyncio
    import pytest
    from fastapi import HTTPException

    main = _make_app(tmp_path, monkeypatch, require_reads="1")
    with TestClient(main.app) as c:
        assert c.get("/api/stream").status_code == 401      # no token → gated

    from control import auth
    # valid token via the ?token= query param → passes (no raise)
    asyncio.run(auth.require_read_token_sse(
        token="test-token-123", authorization=None, x_cc_token=None))
    # wrong query token → denied
    with pytest.raises(HTTPException):
        asyncio.run(auth.require_read_token_sse(
            token="nope", authorization=None, x_cc_token=None))


def test_sse_read_gate_is_noop_when_off(tmp_path, monkeypatch):
    """Default (gate off) is unchanged — the SSE gate is a no-op, no token needed."""
    import asyncio
    _make_app(tmp_path, monkeypatch)   # require_reads default "0"
    from control import auth
    asyncio.run(auth.require_read_token_sse(
        token=None, authorization=None, x_cc_token=None))   # must not raise


def test_audit_log_rotates_past_cap(tmp_path, monkeypatch):
    """An unauthenticated denied-attempt flood must not exhaust disk: the audit
    log rotates to a single .1 backup past the cap, bounding disk to ~2x."""
    from control import audit
    import config as _cfg
    logp = tmp_path / "audit.log"
    monkeypatch.setattr(_cfg, "AUDIT_LOG", logp)
    monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 500)
    for i in range(200):
        audit.record("probe", {"i": i}, "denied", "x" * 50)
    assert logp.exists()
    assert logp.stat().st_size < 3 * 500            # bounded, not unbounded growth
    assert logp.with_suffix(logp.suffix + ".1").exists()   # rotated backup present


def test_push_subscriptions_capped(tmp_path, monkeypatch):
    """Web Push registration is bounded: the store never exceeds the cap.

    It used to keep the most-recent N and drop the OLDEST, which made the cap a
    silencing primitive — see test_push_registration_cannot_evict_a_subscriber.
    The bound is still enforced; only the eviction victim changed."""
    import pytest
    from push import subscriptions, sender
    import config as _cfg
    monkeypatch.setattr(_cfg, "PUSH_SUBS_PATH", tmp_path / "subs.json")
    monkeypatch.setattr(_cfg, "PUSH_MAX_SUBS", 5)
    # Every stored endpoint is vouched for: the flood must be refused without
    # displacing anyone. Unpatched, the M165 probe asks the real network and
    # fcm.googleapis.com answers 404 for this fabricated path — a unit test
    # letting the internet decide who gets evicted.
    monkeypatch.setattr(sender, "probe", lambda sub: 201)
    for i in range(5):
        subscriptions.add({"endpoint": f"https://push.example/{i}"})
    with pytest.raises(subscriptions.StoreFull):
        subscriptions.add({"endpoint": "https://push.example/overflow"})
    assert subscriptions.count() == 5           # bounded, not unbounded growth


# --- The push surface: gating + the eviction primitive -----------------------

def _auth_guards(route):
    """The set of auth dependencies enforced on a route (walks sub-dependencies)."""
    from control.auth import (require_control_token, require_read_token,
                              require_read_token_sse)
    known = {require_control_token, require_read_token, require_read_token_sse}
    found, stack = set(), list(getattr(getattr(route, "dependant", None), "dependencies", []))
    while stack:
        d = stack.pop()
        if d.call in known:
            found.add(d.call)
        stack.extend(d.dependencies)
    return found


# Routes that answer an untokened caller BY DESIGN, each with its reason. Adding
# a route here is a deliberate act; forgetting to gate one is not.
_OPEN_BY_DESIGN = {
    "/api/health": "backend liveness only — no state, no secrets",
    "/api/control/actions": "the closed action enum; informational, no actuation",
}


def test_every_api_route_is_gated_or_explicitly_open(tmp_path, monkeypatch):
    """Enumerate the ACTUAL route table and require every /api route to carry an
    auth dependency or sit in the open-by-design allow-list.

    The read-gate tests assert against hand-written path lists, so a route added
    without a dependency is invisible to them by construction — that is how
    /api/codebase/projects shipped open, and how the whole /api/push/* block did.
    A census of names cannot prove absence; this enumerates the population."""
    from fastapi.routing import APIRoute
    main = _make_app(tmp_path, monkeypatch, require_reads="1")
    ungated = []
    for route in main.app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
            continue
        if route.path in _OPEN_BY_DESIGN or _auth_guards(route):
            continue
        ungated.append(f"{sorted(route.methods)} {route.path}")
    assert not ungated, (
        "these /api routes answer an untokened caller and are not declared "
        "open-by-design:\n  " + "\n  ".join(sorted(ungated)))


def test_push_surface_is_read_gated(tmp_path, monkeypatch):
    """With the read-gate ON, the push routes must not answer an untokened
    caller. /push/subscribe and /push/unsubscribe MUTATE server-side state that
    decides where operator alerts are delivered, so an open surface here is an
    alert-routing control, not a read."""
    main = _make_app(tmp_path, monkeypatch, require_reads="1")
    with TestClient(main.app) as c:
        assert c.get("/api/push/vapid-key").status_code == 401
        assert c.get("/api/push/vapid-key", headers=TOK).status_code == 200
        sub = {"endpoint": "https://push.example/a"}
        assert c.post("/api/push/subscribe", json=sub).status_code == 401
        assert c.post("/api/push/subscribe", json=sub, headers=TOK).status_code == 200
        body = {"endpoint": "https://push.example/a"}
        assert c.post("/api/push/unsubscribe", json=body).status_code == 401
        assert c.post("/api/push/unsubscribe", json=body, headers=TOK).status_code == 200


def test_push_test_requires_the_control_token(tmp_path, monkeypatch):
    """/push/test actuates — it delivers a notification to every registered
    device. That is a control action, so it needs the control token even in the
    default posture where reads are open."""
    main = _make_app(tmp_path, monkeypatch)          # read-gate OFF (default)
    with TestClient(main.app) as c:
        assert c.post("/api/push/test").status_code == 401


def test_push_registration_cannot_evict_a_subscriber(tmp_path, monkeypatch):
    """Registering new subscriptions must never displace an EXISTING one.

    The cap dropped the oldest entry, and the operator's own device is the
    oldest (registered at PWA install). So filling the store silently removed
    the operator from the delivery list and alerts went only to the newcomers —
    the bound meant to stop disk growth became a way to go dark."""
    from push import subscriptions, sender
    import config as _cfg
    monkeypatch.setattr(_cfg, "PUSH_SUBS_PATH", tmp_path / "subs.json")
    monkeypatch.setattr(_cfg, "PUSH_MAX_SUBS", 5)
    # Every stored endpoint is vouched for: the flood must be refused without
    # displacing anyone. Unpatched, the M165 probe asks the real network and
    # fcm.googleapis.com answers 404 for this fabricated path — a unit test
    # letting the internet decide who gets evicted.
    monkeypatch.setattr(sender, "probe", lambda sub: 201)

    operator = "https://fcm.googleapis.com/OPERATOR-DEVICE"
    subscriptions.add({"endpoint": operator})
    refused = 0
    for i in range(50):                      # far past the cap
        try:
            subscriptions.add({"endpoint": f"https://flood.example/{i}"})
        except subscriptions.StoreFull:
            refused += 1                     # full store refuses; it does not evict

    eps = {s["endpoint"] for s in subscriptions.all()}
    assert operator in eps, "the operator's device was evicted by new registrations"
    assert subscriptions.count() <= 5, "the cap must still bound the store"
    assert refused, "a store past capacity must refuse, not silently absorb"


def test_existing_subscriber_can_always_re_register(tmp_path, monkeypatch):
    """A full store must not lock out an endpoint it already holds — browsers
    re-subscribe periodically, and that refresh must not start failing."""
    from push import subscriptions
    import config as _cfg
    monkeypatch.setattr(_cfg, "PUSH_SUBS_PATH", tmp_path / "subs.json")
    monkeypatch.setattr(_cfg, "PUSH_MAX_SUBS", 3)
    for i in range(3):
        subscriptions.add({"endpoint": f"https://push.example/{i}"})
    subscriptions.add({"endpoint": "https://push.example/1", "keys": {"p256dh": "new"}})
    stored = {s["endpoint"]: s for s in subscriptions.all()}
    assert stored["https://push.example/1"].get("keys") == {"p256dh": "new"}
    assert len(stored) == 3


def test_store_full_of_dead_rotations_admits_the_live_endpoint(tmp_path, monkeypatch):
    """M165: push services rotate endpoints, and a rotated-away entry is dead
    at the service while still holding a slot here — nothing proves it dead
    until a delivery happens to 404. A store full of the operator's OWN stale
    rotations then 503s the operator's LIVE endpoint and alerts go nowhere:
    the lockout the refuse-don't-evict cap was never meant to build. On
    StoreFull the store now asks the push service about stored endpoints and
    drops only what the service itself disowns (404/410), then admits the
    newcomer if room opened."""
    from push import subscriptions, sender
    import config as _cfg
    monkeypatch.setattr(_cfg, "PUSH_SUBS_PATH", tmp_path / "subs.json")
    monkeypatch.setattr(_cfg, "PUSH_MAX_SUBS", 3)
    for i in range(3):
        subscriptions.add({"endpoint": f"https://push.example/rotated/{i}"})
    monkeypatch.setattr(sender, "probe", lambda sub: 410)
    total = subscriptions.add({"endpoint": "https://push.example/live"})
    eps = {s["endpoint"] for s in subscriptions.all()}
    assert "https://push.example/live" in eps, (
        "a store full of provably-dead rotations locked out the live endpoint")
    assert total <= 3 and subscriptions.count() <= 3, "the cap must still bound"


def test_store_full_of_live_endpoints_still_refuses(tmp_path, monkeypatch):
    """The prune must not soften the anti-eviction property: when the push
    service vouches for every stored endpoint, the newcomer is refused exactly
    as before and every stored subscriber survives the attempt — pruning the
    merely-unlucky would rebuild the silencing primitive the refusal replaced."""
    import pytest
    from push import subscriptions, sender
    import config as _cfg
    monkeypatch.setattr(_cfg, "PUSH_SUBS_PATH", tmp_path / "subs.json")
    monkeypatch.setattr(_cfg, "PUSH_MAX_SUBS", 3)
    for i in range(3):
        subscriptions.add({"endpoint": f"https://push.example/{i}"})
    monkeypatch.setattr(sender, "probe", lambda sub: 201)
    with pytest.raises(subscriptions.StoreFull):
        subscriptions.add({"endpoint": "https://push.example/new"})
    eps = {s["endpoint"] for s in subscriptions.all()}
    assert eps == {f"https://push.example/{i}" for i in range(3)}, (
        "a live subscriber was dropped to seat a newcomer")


def test_probe_failure_is_not_proof_of_death(tmp_path, monkeypatch):
    """A probe that could not be asked answers nothing (status 0): pruning on
    silence would fabricate the death verdict in exactly the direction that
    silences the operator — a downed network at registration time would purge
    the whole store. Nothing is pruned, and the newcomer is refused loudly."""
    import pytest
    from push import subscriptions, sender
    import config as _cfg
    monkeypatch.setattr(_cfg, "PUSH_SUBS_PATH", tmp_path / "subs.json")
    monkeypatch.setattr(_cfg, "PUSH_MAX_SUBS", 3)
    for i in range(3):
        subscriptions.add({"endpoint": f"https://push.example/{i}"})
    monkeypatch.setattr(sender, "probe", lambda sub: 0)
    with pytest.raises(subscriptions.StoreFull):
        subscriptions.add({"endpoint": "https://push.example/new"})
    assert {s["endpoint"] for s in subscriptions.all()} == {
        f"https://push.example/{i}" for i in range(3)}


# --- Auth: a malformed token must deny, not crash ----------------------------

def test_non_ascii_token_is_denied_and_audited(tmp_path, monkeypatch):
    """secrets.compare_digest raises TypeError on non-ASCII str. Uncaught, that
    turned a 401 into a 500 AND skipped _deny(), so a prober who sends one
    non-ASCII byte left no audit trace — defeating 'token probing must not be
    silent' with a single character.

    Exercised on the dependency directly (as the SSE gate is): httpx refuses to
    encode a non-ASCII header value client-side, so TestClient cannot reach this
    path. A raw client can — uvicorn decodes header bytes as latin-1, so any
    byte in 0x80-0xFF arrives as a non-ASCII str."""
    import asyncio
    import pytest
    from fastapi import HTTPException
    from control import auth

    _make_app(tmp_path, monkeypatch)
    for supplied in ["caf\xe9", "\xff" * 8, "test-token-123\xe9"]:
        with pytest.raises(HTTPException) as ei:
            asyncio.run(auth.require_control_token(
                authorization=None, x_cc_token=supplied))
        assert ei.value.status_code == 401, f"{supplied!r} did not deny cleanly"
    assert "denied" in _audit_text(tmp_path), "the probes left no audit trace"

    # the same byte in the Bearer branch and the SSE query-param branch
    with pytest.raises(HTTPException):
        asyncio.run(auth.require_control_token(
            authorization="Bearer caf\xe9", x_cc_token=None))
    monkeypatch.setattr(__import__("config"), "REQUIRE_TOKEN_FOR_READS", True)
    with pytest.raises(HTTPException):
        asyncio.run(auth.require_read_token_sse(
            token="caf\xe9", authorization=None, x_cc_token=None))


# --- argv flag-injection at the loki-q boundary ------------------------------

def test_reason_never_reaches_argv_as_a_flag(tmp_path, monkeypatch):
    """The demote `reason` is appended to argv, so it must never begin with '-'.

    Stripping dashes and THEN stripping whitespace is order-dependent: the
    second strip re-exposes a dash that the first one hid behind a space, so
    '- -force' survived as '-force' and '--- --json' as '--json' — the exact
    flag the builder appends itself. argv is a list (no shell), so flag
    injection is the only vector left at this boundary."""
    from control import registry
    hostile = ["--force", "- -force", "--- --json", "-\t-rf", "  --  --json  ",
               "-", "--", "- - - -x"]
    for raw in hostile:
        cleaned = registry._reason({"reason": raw})
        assert not cleaned.startswith("-"), f"{raw!r} -> {cleaned!r} leads with a dash"
        argv = registry._SPECS["demote"].build(
            {"action_id": "some_action", "reason": cleaned})
        flags = [a for a in argv[4:] if a.startswith("-") and a != "--json"]
        assert not flags, f"{raw!r} put {flags} into argv as flags"


def test_reason_keeps_a_legitimate_reason_intact(tmp_path, monkeypatch):
    """The dash-strip must not eat ordinary operator prose."""
    from control import registry
    assert registry._reason({"reason": "flapping since 03:00"}) == "flapping since 03:00"
    assert registry._reason({"reason": "a-b-c"}) == "a-b-c"       # inner dashes kept
    assert registry._reason({"reason": ""}) == "operator action (dashboard)"
    assert len(registry._reason({"reason": "x" * 500})) == 200    # still capped
