"""Bridge to L5 Codebase-Memory — the structural index of the whole stack.

L5 (DeusData/codebase-memory-mcp, live since 2026-05-28) keeps an AST graph of
the indexed repos in sync with git. It has no HTTP surface — it's stdio JSON-RPC
MCP, observed by Loki via its CLI. We read it the same way the supervisor's
`retrieval._l5_cli` does: shell the `cli --json <tool>` with a fixed argv (no
operator string in the command), a short timeout, and a size-capped JSON parse.

Confirmed CLI surface used here: `list_projects` (repos with node/edge counts)
and `search_code` (grep-structured search → file/line/content + a directory
histogram). Read-only by definition — the index never modifies source.

Degrades gracefully: a missing binary, non-zero exit, or unparsable output
becomes `available:False` / an `error` note, never an exception.
"""
from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache

_L5_BIN = os.environ.get("CC_L5_BIN", os.path.expanduser("~/.local/bin/codebase-memory-mcp"))
_TIMEOUT = 15
_MAX_OUT = 2 * 1024 * 1024  # cap parsed CLI output


def _cli(tool: str, payload: dict) -> dict:
    """Run one L5 tool and return its inner JSON. Raises on absent binary /
    non-zero exit / unparsable or oversize output (callers convert to notes).

    The MCP CLI wraps results as {"content":[{"text":"<json>"}], "isError":bool};
    we unwrap one level to the tool's own object."""
    proc = subprocess.run(
        [_L5_BIN, "cli", "--json", tool, json.dumps(payload)],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    out = proc.stdout or ""
    if len(out) > _MAX_OUT:
        raise ValueError("L5 output exceeds cap")
    outer = json.loads(out)
    inner = json.loads(outer["content"][0]["text"])
    return inner


def available() -> dict:
    """Is the L5 index reachable? `list_projects` is the liveness gate (it's the
    cheapest real call). Returns {ok, detail, count}."""
    try:
        inner = _cli("list_projects", {})
        projects = inner.get("projects", [])
        return {"ok": True, "detail": "codebase-memory live", "count": len(projects)}
    except FileNotFoundError:
        return {"ok": False, "detail": "codebase-memory-mcp not installed", "count": 0}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"codebase-memory unavailable: {type(exc).__name__}", "count": 0}


@lru_cache(maxsize=1)
def _projects_cached() -> tuple:
    inner = _cli("list_projects", {})
    rows = []
    for p in inner.get("projects", []):
        rows.append((
            p.get("name", "?"),
            p.get("root_path", ""),
            int(p.get("nodes", 0) or 0),
            int(p.get("edges", 0) or 0),
            int(p.get("size_bytes", 0) or 0),
        ))
    return tuple(rows)


def projects() -> dict:
    """The indexed repos with node/edge/size. Cached (the graph changes only on
    git activity). Returns {projects:[...], error}."""
    try:
        rows = _projects_cached()
    except Exception as exc:  # noqa: BLE001
        return {"projects": [], "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    return {
        "projects": [
            {"name": n, "root_path": rp, "nodes": nodes, "edges": edges, "size_bytes": sz,
             "label": _pretty(n)}
            for (n, rp, nodes, edges, sz) in rows
        ],
        "error": None,
    }


def search(project: str, pattern: str, k: int = 40) -> dict:
    """Structural code search within one indexed project. Returns ranked
    file/line/content hits plus the directory histogram L5 computes, so the UI
    can show where matches concentrate. Bounded; degrades to a note."""
    project = (project or "").strip()
    pattern = (pattern or "").strip()
    if not project or not pattern:
        return {"results": [], "directories": {}, "total": 0, "error": "missing project or pattern"}
    try:
        inner = _cli("search_code", {"pattern": pattern, "project": project})
    except Exception as exc:  # noqa: BLE001
        return {"results": [], "directories": {}, "total": 0,
                "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if inner.get("error"):
        return {"results": [], "directories": {}, "total": 0,
                "error": inner.get("error"), "hint": inner.get("hint")}
    results = []
    for r in (inner.get("results") or [])[:k]:
        results.append({
            "file": r.get("file", "?"),
            "line": r.get("line", r.get("start_line")),
            "content": (r.get("content") or "").strip()[:240],
            "qualified_name": r.get("qualified_name") or r.get("node"),
            "label": r.get("label"),
        })
    return {
        "results": results,
        "directories": inner.get("directories") or {},
        "total": inner.get("total_results", len(results)),
        "error": None,
    }


# Friendly repo labels — the index namespaces by absolute path; show the leaf.
_LABELS = {
    "home-operator-projects-loki": "loki (substrate)",
    "home-operator-projects-command-center": "command-center",
}


def _pretty(name: str) -> str:
    if name in _LABELS:
        return _LABELS[name]
    return name.replace("home-operator-projects-", "")
