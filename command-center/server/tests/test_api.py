"""API smoke tests against the fixture via FastAPI TestClient."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURE = Path(__file__).parent / "fixtures" / "state.sample.json"


@pytest.fixture
def client(tmp_path):
    # hermetic: fixture state + temp dirs for push/runtime so tests touch nothing real
    os.environ["CC_STATE_PATH"] = str(FIXTURE)
    os.environ["CC_RUNTIME_DIR"] = str(tmp_path / "runtime")
    os.environ["CC_PUSH_KEYS_PATH"] = str(tmp_path / "vapid.json")
    os.environ["CC_PUSH_SUBS_PATH"] = str(tmp_path / "subs.json")
    os.environ["CC_SKILL_DRAFTS_DIR"] = str(tmp_path / "skill-drafts")
    os.environ["CC_GC_PROPOSALS_DIR"] = str(tmp_path / "gc-proposals")
    os.environ["CC_VAULT_DIR"] = str(tmp_path / "vault")
    os.environ["CC_CONTROL_TOKEN"] = "test-token-123"
    os.environ["CC_CONTROL_DRY_RUN"] = "1"   # API tests never fire real actuators
    (tmp_path / "vault").mkdir()
    (tmp_path / "vault" / "doc.md").write_text("# Doc\n## Routing\nLiteLLM router.\n")
    import importlib
    import config
    importlib.reload(config)
    # modules that captured config values at import time
    import push.vapid as _v
    _v._priv = None
    import docs_router as _d
    _d._index_sig = None
    import control.auth as _a
    _a.reset_cache()
    import main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


TOK = {"X-CC-Token": "test-token-123"}


def test_backend_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_overview_endpoint(client):
    r = client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert len(body["domains"]) == 10
    assert body["overall"] in {"ok", "warn", "crit", "unknown"}


def test_state_endpoint(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    assert "tiers" in r.json()


def test_domain_endpoint(client):
    r = client.get("/api/domain/memory")
    assert r.status_code == 200
    assert "memory" in r.json()


def test_unknown_domain_404(client):
    r = client.get("/api/domain/not_a_domain")
    assert r.status_code == 404


# --- Phase 2 endpoints -------------------------------------------------------

def test_routing_endpoint(client):
    r = client.get("/api/routing")
    assert r.status_code == 200
    assert len(r.json()["components"]) == 3


def test_pending_endpoint(client):
    r = client.get("/api/pending")
    assert r.status_code == 200
    assert "pending" in r.json()


def test_memory_queues_endpoint(client):
    r = client.get("/api/memory/queues")
    assert r.status_code == 200
    body = r.json()
    assert "skill_drafts" in body and "curated_gc" in body


def test_docs_search_endpoint(client):
    r = client.get("/api/docs/search", params={"q": "routing litellm"})
    assert r.status_code == 200
    assert r.json()["results"][0]["heading"] == "Routing"


def test_vapid_key_endpoint(client):
    r = client.get("/api/push/vapid-key")
    assert r.status_code == 200
    assert len(r.json()["applicationServerKey"]) > 20


def test_push_subscribe_and_unsubscribe(client):
    sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}}
    r = client.post("/api/push/subscribe", json=sub)
    assert r.status_code == 200 and r.json()["total"] == 1
    r2 = client.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]})
    assert r2.status_code == 200 and r2.json()["total"] == 0


def test_push_subscribe_rejects_missing_endpoint(client):
    r = client.post("/api/push/subscribe", json={"keys": {}})
    assert r.status_code == 400


# --- Phase 3 control endpoints ----------------------------------------------

def test_control_actions_listed(client):
    r = client.get("/api/control/actions")
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()["actions"]}
    assert "veto" in ids and "t1_offload" in ids


def test_control_requires_token(client):
    r = client.post("/api/control/t1_restore", json={"confirm": True})
    assert r.status_code == 401


def test_control_verify_token(client):
    assert client.get("/api/control/verify", headers=TOK).status_code == 200
    assert client.get("/api/control/verify", headers={"X-CC-Token": "wrong"}).status_code == 401


def test_control_unknown_action_404(client):
    r = client.post("/api/control/launch_missiles", json={"confirm": True}, headers=TOK)
    assert r.status_code == 404


def test_control_requires_confirmation(client):
    # non-dry, no confirm -> 400
    r = client.post("/api/control/t1_restore", json={}, headers=TOK)
    assert r.status_code == 400


def test_control_dry_run_does_not_require_confirm(client):
    r = client.post("/api/control/t1_offload", json={"dry_run": True, "params": {"ngl": 20}}, headers=TOK)
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["would_run"][-1] == "20"


def test_control_confirmed_action_runs_dry_under_global_flag(client):
    # CC_CONTROL_DRY_RUN=1 in fixture -> even confirmed actions are previewed
    r = client.post("/api/control/veto", json={"confirm": True, "params": {"action_id": "offload_t1_reasoning"}}, headers=TOK)
    assert r.status_code == 200
    assert r.json()["dry_run"] is True


def test_control_param_error_400(client):
    r = client.post("/api/control/veto", json={"confirm": True, "params": {"action_id": "bad id!"}}, headers=TOK)
    assert r.status_code == 400


def test_control_audit_gated_and_records(client):
    assert client.get("/api/control/audit").status_code == 401
    client.post("/api/control/t1_offload", json={"dry_run": True, "params": {"ngl": 20}}, headers=TOK)
    r = client.get("/api/control/audit", headers=TOK)
    assert r.status_code == 200
    actions = [e["action"] for e in r.json()["audit"]]
    assert "t1_offload" in actions
