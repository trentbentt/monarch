"""The supervisor bridge must never leak paths / tracebacks to the client (B4)."""
import supervisor_bridge as sb


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
