"""The control surface trusts loki-q's --json verdict, not the exit code (A2)."""
import asyncio
from types import SimpleNamespace

import control.registry as reg


def test_argv_authority_requests_json():
    build = reg._argv_authority("promote")
    argv = build({"action_id": "offload_t1_reasoning"})
    assert argv[-1] == "--json"


def test_run_shell_trusts_structured_json_over_exit_code(monkeypatch):
    """A JSON result of ok:false must be reported as a failure even when the exit
    code is 0 — the old path inferred success from returncode + scraped prose, so a
    'could not promote (already at cap)' looked like success."""
    monkeypatch.setattr(reg.subprocess, "run", lambda a, **k: SimpleNamespace(
        returncode=0,
        stdout='{"ok": false, "action": "promote", "result": "noop", "detail": "already at cap"}',
        stderr=""))
    res = asyncio.run(reg._run_shell(["loki-q", "authority", "promote", "x", "--json"]))
    assert res["ok"] is False
    assert res["result"] == "noop"
    assert "already at cap" in res["detail"]


def test_run_shell_falls_back_to_returncode_for_non_json(monkeypatch):
    """Tools that don't speak JSON (t1_offload/restore) still work off the exit
    code — the JSON parse is best-effort, never required."""
    monkeypatch.setattr(reg.subprocess, "run", lambda a, **k: SimpleNamespace(
        returncode=0, stdout="restored T1 to GPU", stderr=""))
    res = asyncio.run(reg._run_shell(["t1-restore"]))
    assert res["ok"] is True and res["result"] == "ok"
