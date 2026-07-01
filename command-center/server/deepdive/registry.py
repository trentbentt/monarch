"""Deep-dive provider registry — domain key → provider instance.

Mirrors the frontend's RICH map (key → card). A domain with no provider simply
has no deep-dive yet; the route 404s and the UI says so.
"""
from __future__ import annotations

from .base import DeepDiveProvider
from .codebase import CodebaseProvider
from .memory import MemoryProvider
from .workflows import WorkflowsProvider

PROVIDERS: dict[str, DeepDiveProvider] = {
    p.key: p for p in (WorkflowsProvider(), MemoryProvider(), CodebaseProvider())
}


def get_provider(key: str) -> DeepDiveProvider | None:
    return PROVIDERS.get(key)


def list_keys() -> list[str]:
    return list(PROVIDERS.keys())


def deep_payload(key: str, state: dict) -> dict | None:
    """Assemble the full deep-dive payload for a domain, or None if no provider.
    detail() is contracted never to raise; status() is derived from it."""
    p = get_provider(key)
    if p is None:
        return None
    detail = p.detail(state)
    return {
        "key": p.key,
        "label": p.label,
        "status": p.status(state, detail),
        "manifest": p.manifest(),
        "detail": detail,
    }
