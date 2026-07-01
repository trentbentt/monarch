"""Docs router search over a temp vault corpus."""
import config
import docs_router


def _make_vault(tmp_path):
    (tmp_path / "final_memory_architecture.md").write_text(
        "# Memory Architecture\n\n## L7 EverCore\nEverMemOS long-horizon temporal state.\n"
        "## L1 Redis\nHot operational truth.\n"
    )
    (tmp_path / "final_master_summary.md").write_text(
        "# Master Summary\n\n## Routing Layer\nLiteLLM is the router on port 4000.\n"
    )
    arch = tmp_path / "archive"
    arch.mkdir()
    (arch / "old.md").write_text("# Old\n## Redis legacy\nshould be excluded\n")
    return tmp_path


def test_search_finds_section(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAULT_DIR", _make_vault(tmp_path))
    docs_router._index_sig = None  # force rebuild
    res = docs_router.search("evercore long horizon")
    assert res["results"], "expected a match"
    top = res["results"][0]
    assert top["file"] == "final_memory_architecture.md"
    assert "EverCore" in top["heading"]


def test_search_excludes_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAULT_DIR", _make_vault(tmp_path))
    docs_router._index_sig = None
    res = docs_router.search("redis legacy")
    files = {r["file"] for r in res["results"]}
    assert not any("archive" in f for f in files)


def test_search_heading_weighted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAULT_DIR", _make_vault(tmp_path))
    docs_router._index_sig = None
    res = docs_router.search("routing")
    assert res["results"][0]["heading"] == "Routing Layer"


def test_empty_query(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAULT_DIR", _make_vault(tmp_path))
    docs_router._index_sig = None
    assert docs_router.search("")["results"] == []
