"""Deep-dive providers, registry, scope preamble, and the /api/deep route."""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURE = Path(__file__).parent / "fixtures" / "state.sample.json"


# --- Providers (no I/O harness needed) --------------------------------------

def test_registry_lists_known_providers():
    from deepdive import list_keys

    keys = list_keys()
    assert "workflows" in keys
    assert "memory" in keys


def test_unknown_provider_returns_none(state):
    from deepdive import deep_payload, get_provider

    assert get_provider("nope") is None
    assert deep_payload("nope", state) is None


def test_workflows_manifest_shape():
    from deepdive import get_provider

    m = get_provider("workflows").manifest()
    assert m["lede"]
    names = {i["name"] for i in m["items"]}
    assert {"news-pipeline", "evidence-layer"} <= names
    # the registry carries the pipeline stages the supervisor can cite
    np = next(i for i in m["items"] if i["name"] == "news-pipeline")
    assert [s["key"] for s in np["stages"]][0] == "ingest"
    assert m["suggestions"]


def test_workflows_detail_degrades_when_repo_absent(state, tmp_path, monkeypatch):
    # Point every workflow repo at a missing path → present=False, a note, no raise.
    for env in ("CC_PROJ_NEWS_PIPELINE", "CC_PROJ_EVIDENCE_LAYER",
                "CC_PROJ_NEWS_PIPELINE_EVIDENCE_SHIP"):
        monkeypatch.setenv(env, str(tmp_path / "absent"))
    from deepdive import deep_payload

    payload = deep_payload("workflows", state)
    items = payload["detail"]["items"]
    assert items["news-pipeline"]["present"] is False
    assert payload["detail"]["notes"]                       # degradation surfaced
    assert payload["status"] in {"ok", "warn", "crit", "unknown"}


def test_workflows_detail_reads_status_json(state, tmp_path, monkeypatch):
    repo = tmp_path / "news-pipeline"
    repo.mkdir()
    (repo / "status.json").write_text(json.dumps(
        {"last_run": "2999-01-01T00:00:00+00:00", "summary": "all green"}))
    monkeypatch.setenv("CC_PROJ_NEWS_PIPELINE", str(repo))
    from deepdive import deep_payload

    item = deep_payload("workflows", state)["detail"]["items"]["news-pipeline"]
    assert item["reporting"] is True
    assert item["summary"] == "all green"
    assert item["status"] == "ok"          # future timestamp → fresh


def test_memory_provider_proves_interface(state):
    from deepdive import deep_payload

    payload = deep_payload("memory", state)
    assert payload["label"] == "Memory Map"
    assert len(payload["manifest"]["items"]) == 7      # L1..L7
    assert payload["detail"]["facts"]


# --- Scope preamble ----------------------------------------------------------

def test_scope_preamble_composes_from_payload(state):
    import supervisor_bridge as sb
    from deepdive import deep_payload

    pre = sb.scope_preamble(deep_payload("workflows", state))
    assert "Workflows deep-dive" in pre
    assert "news-pipeline" in pre
    assert "read-only" in pre.lower()


def test_scope_preamble_empty_payload_is_blank():
    import supervisor_bridge as sb

    assert sb.scope_preamble(None) == ""
    assert sb.scope_preamble({}) == ""


def test_ask_prepends_preamble(monkeypatch):
    """ask() must put the preamble in front of the question handed to the model."""
    import supervisor_bridge as sb

    captured = {}

    class _Client:
        def ask(self, q):
            captured["q"] = q
            return "ok"

    monkeypatch.setattr(sb, "_load_router_key", lambda: None)
    monkeypatch.setattr(sb, "_supervisor", lambda: (_Client, None))

    out = sb.ask("why stale?", deep=False, preamble="## scope\nWorkflows")
    assert out["error"] is None
    assert captured["q"].startswith("## scope")
    assert "why stale?" in captured["q"]


# --- Route -------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_STATE_PATH", str(FIXTURE))
    monkeypatch.setenv("CC_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CC_VAULT_DIR", str(tmp_path / "vault"))
    (tmp_path / "vault").mkdir()
    import importlib
    import config
    importlib.reload(config)
    import main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def test_deep_route_returns_payload(client):
    r = client.get("/api/deep/workflows")
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "workflows"
    assert body["status"] in {"ok", "warn", "crit", "unknown"}
    assert body["manifest"]["items"]
    assert "facts" in body["detail"]


def test_deep_route_404_for_unknown(client):
    assert client.get("/api/deep/not_a_domain").status_code == 404
