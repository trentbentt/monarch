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
    """Unauthenticated Web Push registration is bounded: the store keeps only the
    most-recent N, dropping the oldest (FIFO)."""
    from push import subscriptions
    import config as _cfg
    monkeypatch.setattr(_cfg, "PUSH_SUBS_PATH", tmp_path / "subs.json")
    monkeypatch.setattr(_cfg, "PUSH_MAX_SUBS", 5)
    for i in range(20):
        subscriptions.add({"endpoint": f"https://push.example/{i}"})
    assert subscriptions.count() == 5
    eps = {s["endpoint"] for s in subscriptions.all()}
    assert "https://push.example/19" in eps     # most-recent kept
    assert "https://push.example/0" not in eps  # oldest evicted
