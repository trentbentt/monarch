"""Deep-dive providers: turn a dashboard domain into a full-page deep-dive."""
from __future__ import annotations

from .base import DeepDiveProvider
from .registry import PROVIDERS, deep_payload, get_provider, list_keys

__all__ = [
    "DeepDiveProvider",
    "PROVIDERS",
    "deep_payload",
    "get_provider",
    "list_keys",
]
