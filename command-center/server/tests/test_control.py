"""Phase 3 control: validation, dispatch (dry-run + real stub), auth, audit."""
import json
import os
import stat

import pytest

import config
from control import acks, audit, registry
from control.registry import ParamError


# --- param validation --------------------------------------------------------

def test_action_id_validation():
    with pytest.raises(ParamError):
        registry._clean("veto", {"action_id": "bad id; rm -rf"})
    with pytest.raises(ParamError):
        registry._clean("approve", {"action_id": ""})
    assert registry._clean("veto", {"action_id": "offload_t1_reasoning"})["action_id"] == "offload_t1_reasoning"


def test_ngl_validation():
    with pytest.raises(ParamError):
        registry._clean("t1_offload", {"ngl": 200})
    with pytest.raises(ParamError):
        registry._clean("t1_offload", {"ngl": "abc"})
    assert registry._clean("t1_offload", {"ngl": 20})["ngl"] == 20
    assert registry._clean("t1_offload", {})["ngl"] is None


def test_workflow_must_be_allow_listed(monkeypatch):
    monkeypatch.setattr(config, "WORKFLOWS", {"news": "webhook/news"})
    with pytest.raises(ParamError):
        registry._clean("workflow_trigger", {"workflow": "evil"})
    assert registry._clean("workflow_trigger", {"workflow": "news"})["workflow"] == "news"


# --- dry-run dispatch (no execution) -----------------------------------------

async def test_dryrun_authority_builds_lokiq_argv():
    r = await registry.execute("approve", {"action_id": "offload_t1_reasoning"}, dry_run=True)
    assert r["dry_run"] is True
    assert r["would_run"][1:] == ["authority", "promote", "offload_t1_reasoning", "--json"]

    r2 = await registry.execute("veto", {"action_id": "offload_t1_reasoning"}, dry_run=True)
    assert r2["would_run"][1:] == ["authority", "veto", "offload_t1_reasoning", "--json"]


async def test_dryrun_t1_offload_includes_ngl():
    r = await registry.execute("t1_offload", {"ngl": 20}, dry_run=True)
    assert r["would_run"][-1] == "20"
    r2 = await registry.execute("t1_offload", {}, dry_run=True)
    assert len(r2["would_run"]) == 1   # no ngl arg


async def test_global_dry_run_forces_preview(monkeypatch):
    monkeypatch.setattr(config, "CONTROL_DRY_RUN", True)
    r = await registry.execute("t1_restore", {}, dry_run=False)
    assert r["dry_run"] is True


# --- real execution via a stubbed binary (safe; not the live actuator) -------

async def test_real_shell_execution_with_stub(tmp_path, monkeypatch):
    stub = tmp_path / "t1-restore"
    stub.write_text("#!/bin/bash\necho restored-ok\nexit 0\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(config, "T1_RESTORE_BIN", str(stub))
    monkeypatch.setattr(config, "CONTROL_DRY_RUN", False)
    r = await registry.execute("t1_restore", {}, dry_run=False)
    assert r["ok"] is True and r["returncode"] == 0
    assert "restored-ok" in r["detail"]


async def test_real_shell_nonzero_exit(tmp_path, monkeypatch):
    stub = tmp_path / "t1-restore"
    stub.write_text("#!/bin/bash\necho boom >&2\nexit 3\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(config, "T1_RESTORE_BIN", str(stub))
    monkeypatch.setattr(config, "CONTROL_DRY_RUN", False)
    r = await registry.execute("t1_restore", {}, dry_run=False)
    assert r["ok"] is False and r["returncode"] == 3


# --- event ack (local, real) -------------------------------------------------

async def test_event_ack_local(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ACK_STORE_PATH", tmp_path / "acks.json")
    monkeypatch.setattr(config, "CONTROL_DRY_RUN", False)
    r = await registry.execute("event_ack", {"event_id": "evt-1"}, dry_run=False)
    assert r["ok"] is True
    assert "evt-1" in acks.acked()


# --- audit -------------------------------------------------------------------

def test_audit_records_and_tails(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.log")
    audit.record("veto", {"action_id": "x"}, "ok", "done")
    audit.record("t1_offload", {"ngl": 20}, "dry_run", "", dry_run=True)
    rows = audit.tail()
    assert len(rows) == 2
    assert rows[0]["action"] == "veto" and rows[0]["result"] == "ok"
    assert rows[1]["dry_run"] is True


def test_list_actions_is_closed_enum():
    ids = {a["id"] for a in registry.list_actions()}
    assert ids == {"approve", "veto", "demote", "t1_offload", "t1_restore",
                   "workflow_trigger", "event_ack"}
