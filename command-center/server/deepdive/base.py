"""The deep-dive provider contract.

A provider turns one dashboard domain into a full-page deep-dive. It answers two
questions, kept deliberately separate so the cheap structural map never pays for
live I/O:

  manifest()      structural truth — what this domain IS. Repos, paths, doctrine,
                  sub-sections, and the questions worth asking the supervisor.
                  Static/derived, no I/O. Cheap enough to build on every request.

  detail(state)   the live slice — freshness, counts, health — assembled from
                  whatever sources the domain uses (Loki state, status.json files,
                  process/mtime checks). EVERY source is wrapped so a missing or
                  broken one yields a note, never an exception.

Both return plain dicts (this backend passes Loki domains through as dicts and
declares models only for what it derives — providers follow the same grain).

The shapes, by convention (documented here, not enforced — keep it light):

  manifest = {
    "lede":      str,                      # one or two sentences: what this is
    "items":     [ {                       # the things inside this domain
        "name":     str,
        "what":     str,                   # plain-language role
        "repo":     str | None,            # filesystem path, ~ ok
        "doctrine": [str],                 # e.g. ["final_master_summary.md §E12"]
        "stages":   [ {"key","label","what"} ],   # optional pipeline
    } ],
    "doctrine":  [str],                    # domain-level doctrine refs
    "suggestions": [str],                  # seed questions for the scoped chat
  }

  detail = {
    "facts":   [ {"label","value","status","sub"} ],   # headline readouts
    "items":   { name: {"status","fresh","note", ...} },# per-item live state
    "notes":   [str],                                   # degradation messages
  }
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class DeepDiveProvider(ABC):
    """One domain's deep-dive. Subclasses set ``key``/``label`` and implement the
    two methods. Instances are cheap and stateless — one per domain in the
    registry."""

    key: str = ""
    label: str = ""

    @abstractmethod
    def manifest(self) -> dict:
        """Structural truth about the domain. No I/O, no live state."""
        raise NotImplementedError

    @abstractmethod
    def detail(self, state: dict) -> dict:
        """Live slice for the domain. Must never raise — wrap every source and
        return a note on failure so the deep-dive degrades instead of 500-ing."""
        raise NotImplementedError

    def status(self, state: dict, detail: dict | None = None) -> str:
        """Roll the domain up to a single light for the header pill. Default:
        worst of the per-fact statuses; providers may override. Returns one of
        ok|warn|crit|unknown."""
        d = detail if detail is not None else self.detail(state)
        levels = [f.get("status") for f in d.get("facts", []) if f.get("status")]
        return _worst(levels)


_RANK = {"ok": 0, "unknown": 1, "warn": 2, "crit": 3}


def _worst(levels) -> str:
    """Worst-wins rollup, but a lone unknown never outranks a real warn/crit —
    mirrors models.worst() so the deep-dive light agrees with the overview dot."""
    levels = [l for l in levels if l]
    if not levels:
        return "unknown"
    return max(levels, key=lambda l: _RANK.get(l, 1))
