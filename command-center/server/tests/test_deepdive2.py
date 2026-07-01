"""Specs 2-4: Memory (retrieval_bridge, vault_reader, MemoryProvider),
Codebase (codebase_bridge, CodebaseProvider), and the dormant Postgres reader
(pg_reader + WorkflowsProvider live enrichment), plus their routes."""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURE = Path(__file__).parent / "fixtures" / "state.sample.json"


# ── Memory: vault_reader ─────────────────────────────────────────────────────

@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_VAULT_DIR", str(tmp_path))
    (tmp_path / "final_master_summary.md").write_text("# Summary\n## §1 Intro\nbody\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "note.md").write_text("# Note\ntext\n")
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "old.md").write_text("# Old\n")   # excluded dir
    (tmp_path / "secret.txt").write_text("not markdown")
    import importlib, config
    importlib.reload(config)
    import vault_reader as vr
    importlib.reload(vr)
    return vr


def test_vault_tree_excludes_nontruth(vault):
    tree = vault.tree()
    names = {c["name"] for c in tree["children"]}
    assert "final_master_summary.md" in names
    assert "sub" in names
    assert "archive" not in names               # excluded dir pruned


def test_vault_read_returns_headings(vault):
    note = vault.read("final_master_summary.md")
    assert note["markdown"].startswith("# Summary")
    assert any(h["text"] == "§1 Intro" for h in note["headings"])


def test_vault_read_rejects_escape_and_nonmd(vault):
    assert vault.read("../../etc/passwd") is None
    assert vault.read("/etc/passwd") is None
    assert vault.read("secret.txt") is None
    assert vault.read("archive/old.md") is None   # excluded scope


# ── Memory: retrieval_bridge degradation ─────────────────────────────────────

def test_retrieval_bridge_degrades_without_loki(monkeypatch):
    import retrieval_bridge as rb

    def boom():
        raise ImportError("no loki")

    monkeypatch.setattr(rb, "_retrieval", boom)
    assert rb.available()["ok"] is False
    out = rb.search_vault("anything")
    assert out["results"] == [] and "unavailable" in out["error"]
    assert rb.route_layers("anything")["layers"] == []


def test_retrieval_bridge_passes_through(monkeypatch):
    import retrieval_bridge as rb

    class _Snip:
        layer, source, locator, score, text = "L3", "vault/x.md", "x.md §chunk 1", 0.12, "hit"

    class _Ret:
        @staticmethod
        def search_vault(q, k=8):
            return [_Snip()]

        @staticmethod
        def route_layers(q):
            return ["L6", "L3"]

    monkeypatch.setattr(rb, "_retrieval", lambda: _Ret)
    out = rb.search_vault("q", k=3)
    assert out["error"] is None and out["results"][0]["score"] == 0.12
    assert rb.route_layers("q")["layers"] == ["L6", "L3"]


def test_memory_provider_doctrine_true(state):
    from deepdive import deep_payload
    payload = deep_payload("memory", state)
    items = list(payload["detail"]["items"].keys())
    assert items[0].startswith("L1") and items[-1].startswith("L7")
    assert any("Redis" in k for k in items) and any("EverCore" in k for k in items)
    assert "capabilities" in payload["manifest"]


# ── Codebase: bridge + provider ──────────────────────────────────────────────

def _fake_cli(tool, payload):
    if tool == "list_projects":
        return {"projects": [
            {"name": "home-operator-projects-loki", "root_path": "/home/operator/projects/loki",
             "nodes": 332, "edges": 828, "size_bytes": 100},
        ]}
    if tool == "search_code":
        return {"results": [{"file": "loki/daemon.py", "line": 10, "content": "def main():"}],
                "directories": {"loki/": 5}, "total_results": 1}
    raise ValueError("unknown")


def test_codebase_bridge_projects_and_search(monkeypatch):
    import codebase_bridge as cb
    monkeypatch.setattr(cb, "_cli", _fake_cli)
    cb._projects_cached.cache_clear()
    pj = cb.projects()
    assert pj["error"] is None and pj["projects"][0]["label"] == "loki (substrate)"
    s = cb.search("home-operator-projects-loki", "main")
    assert s["results"][0]["file"] == "loki/daemon.py"
    assert s["directories"] == {"loki/": 5}


def test_codebase_bridge_degrades(monkeypatch):
    import codebase_bridge as cb

    def boom(tool, payload):
        raise FileNotFoundError("no binary")

    monkeypatch.setattr(cb, "_cli", boom)
    cb._projects_cached.cache_clear()
    assert cb.available()["ok"] is False
    assert cb.projects()["error"]


def test_codebase_provider(monkeypatch):
    import codebase_bridge as cb
    monkeypatch.setattr(cb, "_cli", _fake_cli)
    cb._projects_cached.cache_clear()
    from deepdive import deep_payload
    payload = deep_payload("codebase", {"health": {"components": [{"name": "codebase-memory", "status": "ok"}]}})
    assert payload["status"] == "ok"
    labels = {f["label"] for f in payload["detail"]["facts"]}
    assert {"Indexed repos", "Nodes", "Edges", "L5 index"} <= labels


# ── Postgres reader: dormant + live enrichment ───────────────────────────────

def test_pg_reader_dormant(monkeypatch):
    monkeypatch.delenv("CC_WORKFLOWS_DB_URL", raising=False)
    monkeypatch.delenv("CC_EVIDENCE_DB_URL", raising=False)
    import pg_reader
    pg_reader._available_cached.cache_clear()
    assert pg_reader.available()["ok"] is False
    assert pg_reader.news_runs()["runs"] == []
    assert pg_reader.ledger_summary()["total"] == 0


def test_workflows_dormant_matches_spec1(state, monkeypatch):
    monkeypatch.delenv("CC_WORKFLOWS_DB_URL", raising=False)
    import pg_reader
    pg_reader._available_cached.cache_clear()
    from deepdive import deep_payload
    payload = deep_payload("workflows", state)
    assert "runs" not in payload["detail"]            # no live keys when dormant
    assert "grounding" not in payload["detail"]


def test_workflows_live_enrichment(state, monkeypatch):
    """With pg_reader reporting up, detail gains runs + grounding + facts."""
    import pg_reader
    monkeypatch.setattr(pg_reader, "available", lambda: {"ok": True, "detail": "stub"})
    monkeypatch.setattr(pg_reader, "news_runs", lambda n=14: {"runs": [
        {"run_date": "2026-06-24", "status": "complete", "articles_fetched": 40,
         "articles_used": 30, "api_calls_made": 5, "total_tokens": 1000,
         "errors": [], "brief_path": "/x", "completed_at": "2026-06-24T06:00:00"}], "error": None})
    monkeypatch.setattr(pg_reader, "ledger_summary", lambda days=30: {
        "verdicts": {"confirmed": 9, "refused": 1}, "corrob_rate": 0.91,
        "total": 10, "briefs": 3, "error": None})
    monkeypatch.setattr(pg_reader, "source_authority", lambda top=8: {
        "sources": [{"discovered_via": "reuters", "score": 0.9, "survived": 9, "total": 10}], "error": None})
    from deepdive import deep_payload
    payload = deep_payload("workflows", state)
    d = payload["detail"]
    assert d["runs"][0]["status"] == "complete"
    assert d["grounding"]["corrob_rate"] == 0.91
    labels = {f["label"] for f in d["facts"]}
    assert {"Last run", "Grounding", "Sources"} <= labels


# ── Routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_STATE_PATH", str(FIXTURE))
    monkeypatch.setenv("CC_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CC_VAULT_DIR", str(tmp_path / "vault"))
    (tmp_path / "vault").mkdir()
    (tmp_path / "vault" / "doc.md").write_text("# Doc\n## Routing\nbody\n")
    import importlib, config
    importlib.reload(config)
    import main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def test_memory_vault_routes(client):
    r = client.get("/api/memory/vault/tree")
    assert r.status_code == 200 and r.json()["kind"] == "dir"
    r2 = client.get("/api/memory/vault/note", params={"path": "doc.md"})
    assert r2.status_code == 200 and "Doc" in r2.json()["markdown"]
    assert client.get("/api/memory/vault/note", params={"path": "../../etc/passwd"}).status_code == 404


def test_memory_search_route_degrades(client):
    # No embed/pg in test env → clear note, never a 500.
    r = client.post("/api/memory/search", json={"query": "anything"})
    assert r.status_code == 200
    assert "results" in r.json() and "routing" in r.json()


def test_codebase_routes(client, monkeypatch):
    import codebase_bridge as cb
    monkeypatch.setattr(cb, "_cli", _fake_cli)
    cb._projects_cached.cache_clear()
    r = client.get("/api/codebase/projects")
    assert r.status_code == 200 and r.json()["projects"]
    r2 = client.get("/api/codebase/search", params={"project": "home-operator-projects-loki", "q": "main"})
    assert r2.status_code == 200 and r2.json()["results"]
    assert client.get("/api/codebase/search", params={"project": "", "q": ""}).status_code == 400


def test_deep_routes_for_new_domains(client):
    for dom in ("memory", "codebase"):
        r = client.get(f"/api/deep/{dom}")
        assert r.status_code == 200 and r.json()["key"] == dom
