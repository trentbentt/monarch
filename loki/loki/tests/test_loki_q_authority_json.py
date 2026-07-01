"""The `loki-q authority --json` machine contract (review A2).

The Command Center's control surface parses this structured result instead of
scraping human prose, so these pin the shape and the supported verb set.
"""
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

from loki import authority

_LOKIQ = Path(__file__).resolve().parents[2] / "bin" / "loki-q"


def _load_cli():
    # loki-q has no .py extension, so force a source loader; __name__ != "__main__"
    # means its main() guard does not fire on import.
    loader = importlib.machinery.SourceFileLoader("lokiq_cli", str(_LOKIQ))
    spec = importlib.util.spec_from_loader("lokiq_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr(authority, "AUTHORITY_PATH", tmp_path / "authority.json")
    return _load_cli()


def _last_json(capsys):
    lines = capsys.readouterr().out.strip().splitlines()
    return json.loads(lines[-1])


def test_list_json_shape(cli, capsys):
    cli.cmd_authority(["authority", "list", "--json"])
    obj = _last_json(capsys)
    assert obj["ok"] is True and obj["action"] == "list"
    assert isinstance(obj["records"], list) and obj["records"]   # cold-start seeds


def test_unknown_action_is_structured_failure(cli, capsys):
    with pytest.raises(SystemExit) as e:
        cli.cmd_authority(["authority", "promote", "no_such_action", "--json"])
    assert e.value.code == 1
    obj = _last_json(capsys)
    assert obj["ok"] is False and obj["result"] == "unknown_action"


def test_registry_verbs_are_supported_by_the_cli(cli):
    """The exact subcommands the cc control registry emits must exist in the CLI
    — the seam is now a checkable contract, not positional-string coupling."""
    assert {"promote", "demote", "veto"} <= set(cli.AUTHORITY_SUBCOMMANDS)
