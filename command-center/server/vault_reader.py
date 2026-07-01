"""Read-only L6 vault browser.

Lists and reads the Truth markdown under VAULT_DIR — the human-curated brain made
navigable in the Memory deep-dive. Shares docs_router's scope (same VAULT_DIR,
same _EXCLUDE) so the browser shows exactly the corpus the L3 index covers: no
archive / _artifacts / skills / hermes-skills leakage.

Read-only and path-safe by construction: every read is confined under VAULT_DIR
(resolved-prefix check defeats `..` and symlink escape), restricted to `*.md`,
and size-capped so a pathological file can't blow the response.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import config
from docs_router import _EXCLUDE  # one source of truth for non-Truth dirs

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MAX_BYTES = 512 * 1024  # a Truth note over 512 KB is pathological; refuse to stream it


def _root() -> Path:
    return config.VAULT_DIR


def _in_scope(rel_parts) -> bool:
    """A path is in scope if none of its *directory* parts are excluded."""
    return not any(part in _EXCLUDE for part in rel_parts[:-1])


def _safe_resolve(rel_path: str) -> Optional[Path]:
    """Resolve `rel_path` under VAULT_DIR or return None if it escapes scope,
    isn't a markdown file, or doesn't exist. The resolved-prefix check is what
    makes `../../etc/passwd` and symlink escapes impossible to serve."""
    root = _root().resolve()
    if not rel_path or rel_path.startswith("/"):
        return None
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root)            # raises if candidate escaped root
    except ValueError:
        return None
    if candidate.suffix != ".md" or not candidate.is_file():
        return None
    rel_parts = candidate.relative_to(root).parts
    if not _in_scope(rel_parts):
        return None
    return candidate


def tree() -> dict:
    """The in-scope vault as a nested tree of dirs and notes (relative paths
    only — never leak absolute filesystem paths to the client)."""
    root = _root()
    if not root.is_dir():
        return {"name": "vault", "path": "", "kind": "dir", "children": [], "note": "vault not found"}

    def build(d: Path) -> dict:
        children = []
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            entries = []
        for p in entries:
            rel = p.relative_to(root)
            if p.is_dir():
                if p.name in _EXCLUDE:
                    continue
                node = build(p)
                if node["children"]:           # prune empty dirs (no Truth inside)
                    children.append(node)
            elif p.suffix == ".md":
                children.append({"name": p.name, "path": str(rel), "kind": "note"})
        return {"name": d.name if d != root else "vault",
                "path": "" if d == root else str(d.relative_to(root)),
                "kind": "dir", "children": children}

    return build(root)


def read(rel_path: str) -> Optional[dict]:
    """Return a note's markdown + its heading outline, or None if out of scope /
    absent / too large."""
    path = _safe_resolve(rel_path)
    if path is None:
        return None
    try:
        if path.stat().st_size > _MAX_BYTES:
            return {"path": rel_path, "markdown": "", "headings": [],
                    "note": "note exceeds size cap; open it on disk"}
        text = path.read_text(errors="replace")
    except OSError:
        return None
    headings = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = _HEADING_RE.match(line)
        if m:
            headings.append({"level": len(m.group(1)), "text": m.group(2).strip(), "line": i})
    return {"path": rel_path, "markdown": text, "headings": headings}
