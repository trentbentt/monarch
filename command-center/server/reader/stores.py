"""Read the Hermes draft-state stores directly off disk.

Mirrors loki-q's cmd_skill_drafts / cmd_curated_gc (it reads the filesystem,
not the daemon), so the dashboard shows the same queues without parsing CLI text:
  - skill-drafts:  ~/.hermes/skill-drafts/<name>/SKILL.md  (desc from YAML)
  - curated-gc:    ~/.hermes/gc-proposals/*.json           (id/class/kind/target/rationale)

All functions are read-only and degrade to empty/None rather than raising.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import List, Optional

import config

_DESC_RE = re.compile(r"^description:\s*(.+)$", re.M)


def _stale(age_s: Optional[float]) -> bool:
    return age_s is not None and age_s > config.STALE_DAYS * 86400


def _draft_summary(skill_md: Path) -> Optional[str]:
    try:
        text = skill_md.read_text(errors="replace")
    except OSError:
        return None
    m = _DESC_RE.search(text)
    if m:
        return m.group(1).strip().strip('"').strip("'")[:120]
    for line in text.splitlines():
        s = line.strip()
        if not s or s == "---" or s.startswith("name:"):
            continue
        return s.lstrip("# ").strip()[:120]
    return None


def skill_drafts() -> dict:
    d = config.SKILL_DRAFTS_DIR
    if not d.is_dir():
        return {"available": False, "items": [], "dir": str(d)}
    now = time.time()
    items = []
    for name in sorted(e for e in (p.name for p in d.iterdir()) if not e.startswith(".")):
        skill_md = d / name / "SKILL.md"
        target = skill_md if skill_md.is_file() else d / name
        try:
            age = now - target.stat().st_mtime
        except OSError:
            age = None
        items.append({
            "name": name,
            "has_skill_md": skill_md.is_file(),
            "age_seconds": int(age) if age is not None else None,
            "stale": _stale(age),
            "summary": _draft_summary(skill_md) if skill_md.is_file() else None,
        })
    return {"available": True, "items": items, "dir": str(d)}


def curated_gc() -> dict:
    d = config.GC_PROPOSALS_DIR
    if not d.is_dir():
        return {"available": False, "items": [], "dir": str(d)}
    now = time.time()
    items = []
    for f in sorted(p for p in d.iterdir() if p.suffix == ".json"):
        try:
            p = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        try:
            age = now - f.stat().st_mtime
        except OSError:
            age = None
        items.append({
            "id": p.get("id"),
            "class": p.get("class"),
            "kind": p.get("kind"),
            "target": p.get("target"),
            "rationale": p.get("rationale"),
            "age_seconds": int(age) if age is not None else None,
            "stale": _stale(age),
        })
    return {"available": True, "items": items, "dir": str(d)}


def memory_queues() -> dict:
    return {"skill_drafts": skill_drafts(), "curated_gc": curated_gc()}
