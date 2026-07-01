"""Memory deep-dive provider — doctrine-true seven-layer architecture.

Spec 1 shipped this as a worked example with placeholder layer names. Spec 2
corrects it to the doctrine-true L1-L7 of `final_memory_architecture.md` v20 §7
(each layer's name, its §3 class — Truth / Index / Memory — its locus, and its
§11 failure mode), and advertises the interactive capabilities the bespoke
front-end offers: the L6 vault browser and L3 semantic search.

Live detail still derives only from the `state.memory` observation slice (§10);
the interactive reads (vault files, pgvector) happen through their own endpoints
(`vault_reader`, `retrieval_bridge`), never here.
"""
from __future__ import annotations

from .base import DeepDiveProvider, _worst

# Doctrine-true layers. `cls` is the §3 four-layer class; `locus` is where it
# physically lives; `fail` is the §11 failure-mode headline for its panel.
_LAYERS = [
    {"key": "L1", "name": "Redis", "cls": "Truth", "locus": "redis :6379 (hot operational)",
     "what": "Hot operational state — last-touched context, live counters.",
     "fail": "§11.1 — on Redis loss, hot state is rebuilt from L2; transient."},
    {"key": "L2", "name": "Postgres", "cls": "Truth", "locus": "monarch-postgres (structured relational)",
     "what": "Structured relational truth — the durable system-of-record tables.",
     "fail": "§11.2 — Postgres down blocks structured reads; Loki surfaces a tier warning."},
    {"key": "L3", "name": "pgvector", "cls": "Index", "locus": "monarch-postgres · vault_note_chunks",
     "what": "Semantic index over the embedded vault (nomic-embed, 768-dim).",
     "fail": "§11.3 — embed service or index down → search degrades; re-indexer resumes."},
    {"key": "L4", "name": "Hermes Agent", "cls": "Memory", "locus": "~/.hermes (agent working memory)",
     "what": "Agent working memory — session recall, file-backed MEMORY/USER.",
     "fail": "§11.4 — Hermes down → session recall unavailable; vault Truth unaffected."},
    {"key": "L5", "name": "Codebase-Memory", "cls": "Index", "locus": "codebase-memory-mcp (structural)",
     "what": "Structural code index — the symbol/call graph across the repos.",
     "fail": "§11.5 — index stale/absent → structural queries degrade; source unaffected."},
    {"key": "L6", "name": "Obsidian Vault", "cls": "Truth", "locus": "~/vault (human-curated 2nd brain)",
     "what": "Human-curated knowledge — the Truth documents and doctrine.",
     "fail": "§11.6 — vault unreadable → doctrine reads fail; the authoritative source."},
    {"key": "L7", "name": "EverCore", "cls": "Memory", "locus": "evercore :1995 (long-horizon temporal)",
     "what": "Long-horizon temporal memory — episodes and trajectory over time.",
     "fail": "§11.7 — EverCore down → temporal recall unavailable; recent state unaffected."},
]
_BY_KEY = {l["key"]: l for l in _LAYERS}
_ORDER = [l["key"] for l in _LAYERS]


def _layer_status(l: dict) -> str:
    if not l:
        return "unknown"
    if l.get("anomaly"):
        return "warn"
    h = (l.get("health") or l.get("health_signal") or "").lower()
    if any(w in h for w in ("unhealth", "down", "dead")):
        return "crit"
    if any(w in h for w in ("degrad", "idle", "stale")):
        return "warn"
    if any(w in h for w in ("ok", "health")):
        return "ok"
    return "unknown"


def _semantic_available() -> bool:
    """Is L3 semantic search reachable? Cheap import check via the bridge; the
    front-end uses this to decide whether to offer the search box."""
    try:
        import retrieval_bridge
        return bool(retrieval_bridge.available().get("ok"))
    except Exception:  # noqa: BLE001
        return False


class MemoryProvider(DeepDiveProvider):
    key = "memory"
    label = "Memory Map"

    def manifest(self) -> dict:
        return {
            "lede": "The seven-layer memory substrate — L1 Redis up to L7 EverCore. "
                    "Three classes: Truth (the record), Index (how it's found), "
                    "Memory (what persists). Loki is the Arbiter; it reads the "
                    "layers, it does not own their content.",
            "items": [
                {
                    "name": f"{l['key']} {l['name']}",
                    "what": f"[{l['cls']}] {l['what']}",
                    "repo": l["locus"],
                    "doctrine": ["final_memory_architecture.md §7"],
                    "stages": [],
                }
                for l in _LAYERS
            ],
            "doctrine": ["final_memory_architecture.md §3 (four layers)",
                         "final_memory_architecture.md §7 (per-layer detail)",
                         "final_memory_architecture.md §11 (failure modes)"],
            "capabilities": {
                "vault_browser": True,
                "semantic_search": _semantic_available(),
            },
            "suggestions": [
                "Which memory layer is least healthy right now?",
                "What backs L3, and when did it last sync?",
                "Walk me through what each layer holds.",
                "Are the curated-GC or skill-draft queues backed up?",
            ],
        }

    def detail(self, state: dict) -> dict:
        mem = (state or {}).get("memory", {}) or {}
        live = mem.get("layers", {}) or {}
        items: dict = {}
        levels: list = []
        for key in _ORDER:
            meta = _BY_KEY[key]
            ll = live.get(key, {}) or {}
            st = _layer_status(ll) if ll else "unknown"
            items[f"{key} {meta['name']}"] = {
                "status": st,
                "layer": key,
                "name": meta["name"],
                "cls": meta["cls"],
                "locus": meta["locus"],
                "what": meta["what"],
                "fail": meta["fail"],
                "response_ms": ll.get("response_ms"),
                "role": ll.get("role") or ll.get("anomaly"),
                "reporting": bool(ll),
            }
            levels.append(st)

        reporting = sum(1 for i in items.values() if i["reporting"])
        gc_total = mem.get("gc_proposals_total", 0)
        sd_total = mem.get("skill_drafts_total", 0)
        facts = [
            {"label": "Layers", "value": f"{reporting}/{len(_LAYERS)}",
             "status": _worst(levels), "sub": "reporting"},
            {"label": "GC proposals", "value": str(gc_total),
             "status": "ok", "sub": "curated tier"},
            {"label": "Skill drafts", "value": str(sd_total),
             "status": "ok", "sub": "pending"},
        ]
        notes = [] if reporting else ["Memory layers not reporting in current state."]
        return {"facts": facts, "items": items, "notes": notes}
