"""supervisor_bridge regressions.

Two independent guarantees:
  * router-key loading: api_keys.env is shell-sourced (`export NAME=value`), so
    the key loader must strip the `export ` prefix. Without it the master key is
    never lifted, the request to the local LiteLLM router goes out
    unauthenticated, the router 401s, and the loki client mislabels the 401 as an
    unreachable router ("supervisor model offline — router unreachable").
  * the bridge must never leak paths / tracebacks to the client (review B4).
"""
import os

import config
import supervisor_bridge as sb


def _write_env(tmp_path, text):
    p = tmp_path / "api_keys.env"
    p.write_text(text)
    return p


def test_load_router_key_handles_export_prefix(tmp_path, monkeypatch):
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.setattr(
        config, "API_KEYS_ENV",
        _write_env(tmp_path, 'export FOO=bar\nexport LITELLM_MASTER_KEY="sk-secret"\n'),
    )
    sb._load_router_key()
    assert os.environ.get("LITELLM_MASTER_KEY") == "sk-secret"


def test_load_router_key_handles_bare_assignment(tmp_path, monkeypatch):
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.setattr(
        config, "API_KEYS_ENV",
        _write_env(tmp_path, "LITELLM_API_KEY=sk-bare\n"),
    )
    sb._load_router_key()
    assert os.environ.get("LITELLM_API_KEY") == "sk-bare"


def test_load_router_key_ignores_similarly_named_vars(tmp_path, monkeypatch):
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.setattr(
        config, "API_KEYS_ENV",
        _write_env(tmp_path, "export LITELLM_MASTER_KEY_BACKUP=nope\n"),
    )
    sb._load_router_key()
    assert os.environ.get("LITELLM_MASTER_KEY") is None


def _boom():
    raise ImportError("boom loading from /home/secret/projects/loki")


def test_import_failure_returns_generic_note_without_paths(monkeypatch):
    monkeypatch.setattr(sb, "_supervisor", _boom)
    res = sb.ask("anything")
    assert res["error"] == "import_failed"
    assert "see server logs" in res["answer"]
    # the absolute LOKI_ROOT path and the raw exception must NOT reach the client
    assert str(sb.LOKI_ROOT) not in res["answer"]
    assert "boom" not in res["answer"]
    assert "/home/secret" not in res["answer"]
