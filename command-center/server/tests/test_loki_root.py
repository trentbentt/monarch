"""CC_LOKI_ROOT must default to the IN-REPO loki tree (review H10).

The bridges previously defaulted to ~/projects/loki — a checkout OUTSIDE this
monorepo — so a fresh clone degraded to "supervisor unavailable" and the
conformance test validated a different loki tree than production imported. The
default now resolves to the in-repo loki/, and both bridges read the single
config.LOKI_ROOT (no divergent literals).
"""
import importlib


def test_loki_root_defaults_to_in_repo_tree(monkeypatch):
    monkeypatch.delenv("CC_LOKI_ROOT", raising=False)
    import config
    importlib.reload(config)
    assert config.LOKI_ROOT.name == "loki"
    assert (config.LOKI_ROOT / "loki" / "authority.py").is_file(), \
        "default LOKI_ROOT must point at the in-repo loki package, not ~/projects/loki"


def test_bridges_share_one_loki_root(monkeypatch):
    monkeypatch.delenv("CC_LOKI_ROOT", raising=False)
    import config
    import supervisor_bridge
    import retrieval_bridge
    importlib.reload(config)
    importlib.reload(supervisor_bridge)
    importlib.reload(retrieval_bridge)
    assert supervisor_bridge.LOKI_ROOT == config.LOKI_ROOT
    assert retrieval_bridge.LOKI_ROOT == config.LOKI_ROOT
