"""state.json contract — the StateStore snapshot domains.

Loki's daemon is the single writer of ``~/.local/state/loki/state.json``; the
Command Center is a pure reader (``state_watcher`` + ``derive``). This is the
other cross-repo seam previously held together by convention — a domain rename
in Loki would silently break the Command Center's derivation. Listed here so
that rename is a contract change with a failing test, not a runtime surprise.
"""
from __future__ import annotations

# The schema version the Command Center's derivation is written against. Loki's
# SystemModel.schema_version must equal this (conformance-tested), so a version
# bump is a coordinated contract change with a failing test — not an inert label.
# The reader also warns on a live mismatch (version skew) rather than silently
# rendering a reshaped state as if it were current.
STATE_SCHEMA_VERSION = "0.1.0"


def schema_skew(state_version) -> str | None:
    """Return a human-readable skew note if the live state's schema_version
    differs from the contract, else None. A missing version counts as skew."""
    if state_version != STATE_SCHEMA_VERSION:
        return (f"state.json schema_version {state_version!r} != contract "
                f"{STATE_SCHEMA_VERSION!r}; Command Center derivation may be stale")
    return None


STATE_DOMAINS = frozenset({
    "schema_version",
    "last_updated",
    "daemon_pid",
    "tiers",
    "resources",
    "health",
    "hardware",
    "workloads",
    "quotas",
    "schedule",
    "memory",
    "decisions",
    "events",
    "operator",
})
