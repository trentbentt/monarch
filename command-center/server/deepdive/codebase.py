"""Codebase deep-dive provider — a frontend over L5 Codebase-Memory.

`manifest()` is static structural truth (the repos and their roles + doctrine) so
it stays cheap — the scope preamble calls it on every supervisor turn. `detail()`
does the live L5 read (node/edge counts per repo + health), via `codebase_bridge`.
Read-only: L5 is an index layer (§7.5, "the graph never modifies source code").
"""
from __future__ import annotations

from .base import DeepDiveProvider

# Static role map for the indexed repos — what each project IS, so the supervisor
# scope and the UI can frame a repo without an L5 round-trip.
_ROLES = {
    "loki (substrate)": "The monarch substrate — daemon, supervisor, memory routing, inference tiers.",
    "evidence-layer": "Deterministic accuracy substrate — the grounded ledger that refuses ungrounded claims.",
    "news-pipeline": "Deterministic news pipeline — ingest → verify → render.",
    "financial": "Financial pipeline (strategy-gated).",
    "leads": "Leads tooling.",
    "design": "Design assets and explorations.",
    "content": "Content workspace.",
    "consultancy": "Consultancy workspace.",
    "exploratory-coding": "Exploratory coding sandbox.",
}


def _health(state: dict) -> str:
    for c in (state or {}).get("health", {}).get("components", []) or []:
        if c.get("name") == "codebase-memory":
            s = (c.get("status") or "").lower()
            if s in ("ok", "healthy", "up"):
                return "ok"
            if s in ("warn", "degraded"):
                return "warn"
            if s in ("crit", "down", "dead", "error"):
                return "crit"
    return "unknown"


class CodebaseProvider(DeepDiveProvider):
    key = "codebase"
    label = "Codebase Map"

    def manifest(self) -> dict:
        return {
            "lede": "The structural memory of the whole stack — the indexed repos "
                    "and the symbol/call graph L5 keeps in sync with git. Search it, "
                    "and dive into any file with the supervisor.",
            "items": [
                {"name": name, "what": role, "repo": None,
                 "doctrine": ["final_memory_architecture.md §7.5"], "stages": []}
                for name, role in _ROLES.items()
            ],
            "doctrine": ["final_memory_architecture.md §7.5 (L5 Codebase-Memory)"],
            "suggestions": [
                "Where is the deep-dive payload assembled?",
                "Search the substrate for the supervisor scope preamble.",
                "Which repo holds the evidence ledger, and what guards it?",
                "Explain how routing decides which memory layers to read.",
            ],
        }

    def detail(self, state: dict) -> dict:
        import codebase_bridge
        health = _health(state)
        data = codebase_bridge.projects()
        repos = data.get("projects", [])
        total_nodes = sum(r["nodes"] for r in repos)
        total_edges = sum(r["edges"] for r in repos)

        items = {}
        for r in repos:
            items[r["label"]] = {
                "status": "ok" if r["nodes"] else "unknown",
                "name": r["label"],
                "raw_name": r["name"],
                "nodes": r["nodes"],
                "edges": r["edges"],
                "root_path": r["root_path"],
                "role": _ROLES.get(r["label"], ""),
            }

        facts = [
            {"label": "Indexed repos", "value": str(len(repos)),
             "status": "ok" if repos else "unknown", "sub": "in L5"},
            {"label": "Nodes", "value": f"{total_nodes:,}", "status": "ok", "sub": "symbols"},
            {"label": "Edges", "value": f"{total_edges:,}", "status": "ok", "sub": "relations"},
            {"label": "L5 index", "value": _WORD.get(health, "Unknown"),
             "status": health, "sub": "codebase-memory"},
        ]
        notes = []
        if data.get("error"):
            notes.append(f"L5 read: {data['error']}")
        if not repos and not data.get("error"):
            notes.append("No repos indexed — codebase-memory may not be installed.")
        return {"facts": facts, "items": items, "notes": notes,
                "capabilities": {"search": bool(repos)}}

    def status(self, state: dict, detail: dict | None = None) -> str:
        return _health(state)


_WORD = {"ok": "Live", "warn": "Degraded", "crit": "Down", "unknown": "Unknown"}
