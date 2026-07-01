"""Docs router — "where's the doc for X" over the L6 vault.

Builds a lightweight heading index over the vault's Truth markdown (top-level +
shallow), excluding non-Truth dirs per vault scope (archive / _artifacts / skills
/ hermes-skills). Returns file + section heading + line + snippet, ranked by term
overlap. Index is cached and invalidated on directory mtime change.

This is the read-only Phase-2 surface; it does not modify the vault.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import List, Optional

import config

_EXCLUDE = {"archive", "_artifacts", "skills", "hermes-skills", ".git", ".obsidian"}
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_WORD_RE = re.compile(r"[a-z0-9]+")

# module-level cache
_index: List[dict] = []
_index_built_at: float = 0.0
_index_sig: Optional[tuple] = None


def _md_files() -> List[Path]:
    root = config.VAULT_DIR
    if not root.is_dir():
        return []
    out = []
    for p in root.rglob("*.md"):
        rel_parts = p.relative_to(root).parts
        if any(part in _EXCLUDE for part in rel_parts[:-1]):
            continue
        out.append(p)
    return out


def _dir_signature(files: List[Path]) -> tuple:
    return tuple(sorted((str(f), int(f.stat().st_mtime)) for f in files if f.exists()))


def _tokens(text: str) -> set:
    return set(_WORD_RE.findall(text.lower()))


def _build_index() -> None:
    global _index, _index_built_at, _index_sig
    files = _md_files()
    sig = _dir_signature(files)
    if sig == _index_sig and _index:
        return
    entries: List[dict] = []
    for f in files:
        try:
            lines = f.read_text(errors="replace").splitlines()
        except OSError:
            continue
        rel = str(f.relative_to(config.VAULT_DIR))
        current = {"heading": rel, "line": 1, "body": []}
        sections = [current]
        for i, line in enumerate(lines, 1):
            m = _HEADING_RE.match(line)
            if m:
                current = {"heading": m.group(2).strip(), "line": i, "body": []}
                sections.append(current)
            else:
                if line.strip():
                    current["body"].append(line.strip())
        for sec in sections:
            body = " ".join(sec["body"])[:600]
            entries.append({
                "file": rel,
                "heading": sec["heading"],
                "line": sec["line"],
                "snippet": body[:240],
                "_tok": _tokens(sec["heading"] + " " + body),
            })
    _index = entries
    _index_sig = sig
    _index_built_at = time.time()


def search(query: str, limit: int = 12) -> dict:
    _build_index()
    q = _tokens(query)
    if not q:
        return {"query": query, "results": [], "indexed_sections": len(_index)}
    scored = []
    for e in _index:
        overlap = len(q & e["_tok"])
        if not overlap:
            continue
        # weight heading matches higher
        heading_hits = len(q & _tokens(e["heading"]))
        score = overlap + heading_hits * 2
        scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [{
        "file": e["file"], "heading": e["heading"], "line": e["line"],
        "snippet": e["snippet"], "score": s,
    } for s, e in scored[:limit]]
    return {"query": query, "results": results, "indexed_sections": len(_index)}
