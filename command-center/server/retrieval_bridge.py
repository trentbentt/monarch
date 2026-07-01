"""Bridge to the Loki memory-retrieval layer (read-only).

The Memory deep-dive reads the substrate through THE SAME module the supervisor
uses — `loki.supervisor.retrieval` — instead of re-implementing embedding or SQL.
That module is read-only by construction (it only SELECTs L3, opens SQLite ro for
L4, reads doctrine files for L6, runs a read CLI for L5). We expose just the
slices the dashboard needs and convert its `Snippet` dataclass to plain dicts.

Degrades gracefully, exactly like supervisor_bridge: if loki can't be imported
(tree moved/renamed) or a backend is down (embed service, pgvector), the caller
gets a clear note instead of an exception — the panel renders "unavailable",
never a 500.
"""
from __future__ import annotations

import sys

# Same knob the supervisor bridge uses, so both reach one Loki tree.
from config import LOKI_ROOT   # single source of truth (defaults to in-repo loki/)


def _retrieval():
    """Lazy import so a missing/renamed loki tree degrades to a clear message
    instead of crashing the API at import time."""
    if str(LOKI_ROOT) not in sys.path:
        sys.path.insert(0, str(LOKI_ROOT))
    from loki.supervisor import retrieval  # noqa: WPS433
    return retrieval


def _snip_dict(s) -> dict:
    """loki Snippet -> the plain shape the frontend renders."""
    return {
        "layer": getattr(s, "layer", "?"),
        "source": getattr(s, "source", ""),
        "locator": getattr(s, "locator", ""),
        "score": float(getattr(s, "score", 0.0) or 0.0),
        "text": getattr(s, "text", ""),
    }


def available() -> dict:
    """Can we reach the retrieval layer at all? Import-level check only — the
    individual backends (embed service, pgvector) are probed by their actual
    calls and degrade there, so this stays fast (no network)."""
    try:
        _retrieval()
        return {"ok": True, "detail": "loki retrieval importable"}
    except Exception as exc:  # noqa: BLE001 — import/env failure is the answer, not a crash
        return {"ok": False, "detail": f"loki retrieval unavailable: {exc}"}


def search_vault(query: str, k: int = 8) -> dict:
    """L3 semantic search over the embedded vault (`vault_note_chunks`). Returns
    nearest-first results with distance, or a clear error note. Blocking (embed
    round-trip + SQL) — callers run it off the event loop."""
    query = (query or "").strip()
    if not query:
        return {"results": [], "error": "empty query", "query": query}
    try:
        retrieval = _retrieval()
    except Exception as exc:  # noqa: BLE001
        return {"results": [], "error": f"retrieval layer unavailable: {exc}", "query": query}
    try:
        snips = retrieval.search_vault(query, k=max(1, min(int(k or 8), 25)))
    except Exception as exc:  # noqa: BLE001 — embed/pg down → degrade, never raise
        return {
            "results": [],
            "error": f"semantic search unavailable: {type(exc).__name__}: {str(exc)[:120]}",
            "query": query,
        }
    return {"results": [_snip_dict(s) for s in snips], "error": None, "query": query}


def route_layers(query: str) -> dict:
    """Which memory layers this question would touch (§8.6 verb heuristic).
    Informational — shown as a hint beside L3 results. Never raises."""
    query = (query or "").strip()
    if not query:
        return {"layers": [], "error": None}
    try:
        retrieval = _retrieval()
        return {"layers": list(retrieval.route_layers(query)), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"layers": [], "error": str(exc)}
