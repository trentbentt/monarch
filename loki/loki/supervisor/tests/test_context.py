"""load_ledger() must read the keys authority.py actually persists
(clean_run_count / state), not the legacy clean_runs / lifecycle names that
never existed on disk. With the wrong keys the supervisor's grounded
## authority_ledger block was always null, so the model confabulated trust
state exactly where it is supposed to cite it (review HIGH finding)."""

import json

from loki.supervisor import context


def test_load_ledger_reads_persisted_keys(tmp_path, monkeypatch):
    p = tmp_path / "authority.json"
    p.write_text(json.dumps({"actions": {
        "offload_t1_reasoning": {
            "current_tier": "tier_2",
            "clean_run_count": 7,
            "state": "eligible",
        }
    }}))
    monkeypatch.setattr(context, "LEDGER_PATH", p)

    rows = context.load_ledger()
    assert len(rows) == 1
    row = rows[0]
    assert row["action_id"] == "offload_t1_reasoning"
    assert row["clean_runs"] == 7          # mapped from clean_run_count, not null
    assert row["lifecycle"] == "eligible"  # mapped from state, not null


def test_load_ledger_tolerates_legacy_keys(tmp_path, monkeypatch):
    p = tmp_path / "authority.json"
    p.write_text(json.dumps({"actions": {
        "x": {"current_tier": "tier_3", "clean_runs": 3, "lifecycle": "cold_start"},
    }}))
    monkeypatch.setattr(context, "LEDGER_PATH", p)

    row = context.load_ledger()[0]
    assert row["clean_runs"] == 3
    assert row["lifecycle"] == "cold_start"


def test_load_ledger_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "LEDGER_PATH", tmp_path / "nope.json")
    assert context.load_ledger() == []
