"""Memory-queue stores read from the filesystem like loki-q does."""
import json
import os
import time

import config
from reader import stores


def test_skill_drafts_parsed(tmp_path, monkeypatch):
    d = tmp_path / "skill-drafts"
    (d / "make-fixture").mkdir(parents=True)
    (d / "make-fixture" / "SKILL.md").write_text(
        "---\nname: make-fixture\ndescription: Generate a sanitised state fixture\n---\nbody"
    )
    monkeypatch.setattr(config, "SKILL_DRAFTS_DIR", d)
    out = stores.skill_drafts()
    assert out["available"] is True
    assert out["items"][0]["name"] == "make-fixture"
    assert out["items"][0]["summary"] == "Generate a sanitised state fixture"
    assert out["items"][0]["stale"] is False


def test_skill_drafts_stale_flag(tmp_path, monkeypatch):
    d = tmp_path / "skill-drafts"
    (d / "old").mkdir(parents=True)
    f = d / "old" / "SKILL.md"
    f.write_text("description: old one")
    old = time.time() - (config.STALE_DAYS + 5) * 86400
    os.utime(f, (old, old))
    monkeypatch.setattr(config, "SKILL_DRAFTS_DIR", d)
    out = stores.skill_drafts()
    assert out["items"][0]["stale"] is True


def test_skill_drafts_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SKILL_DRAFTS_DIR", tmp_path / "nope")
    out = stores.skill_drafts()
    assert out["available"] is False
    assert out["items"] == []


def test_curated_gc_parsed(tmp_path, monkeypatch):
    d = tmp_path / "gc-proposals"
    d.mkdir()
    (d / "p1.json").write_text(json.dumps({
        "id": "gc-001", "class": "skills", "kind": "merge",
        "target": "a+b", "rationale": "near-duplicate procedures",
    }))
    monkeypatch.setattr(config, "GC_PROPOSALS_DIR", d)
    out = stores.curated_gc()
    assert out["available"] is True
    it = out["items"][0]
    assert it["id"] == "gc-001" and it["kind"] == "merge"
    assert it["rationale"].startswith("near-duplicate")


def test_curated_gc_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GC_PROPOSALS_DIR", tmp_path / "nope")
    assert stores.curated_gc()["available"] is False
