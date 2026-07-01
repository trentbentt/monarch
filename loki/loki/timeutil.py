"""Shared time helpers.

Single source for the UTC clock used across the engine and the authority
ledger, so the two never drift on how 'now' is constructed.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)
