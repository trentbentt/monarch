"""
Context builder — assembles the grounded, read-only context block the supervisor
LLM reasons over. This is the disk-is-truth enforcement in code: the model only
ever sees values that were read fresh from state.json / authority.json / doctrine
this turn, so "ground every claim in the snapshot" is structurally possible.

Read-only by construction:
  • state via StateStore.load_from_disk() — reads STATE_PATH, never the live store,
    never writes.
  • ledger via a direct read of authority.json — never the live AuthorityLedger
    object (no risk of mutating trust counters).
  • doctrine via plain file reads of the canonical vault files, bounded in size.

Nothing here imports the writer thread or the gate's mutators.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from ..actions import ACTIONS
from ..state import StateStore
from . import retrieval

logger = logging.getLogger(__name__)

LEDGER_PATH = Path(os.environ.get(
    "LOKI_AUTHORITY_PATH",
    Path.home() / ".local/state/loki/authority.json",
))

# The block's own first line, named once. `client.py` finds the grounded block in
# an outgoing message list by this heading in order to hand it to the reply checks
# (M199) — a second hand-copied literal there would rot silently the day this
# wording changes, and the check would go quiet rather than red (M101).
CONTEXT_HEADING = "# GROUNDED CONTEXT"

# Canonical doctrine the supervisor may cite. Kept as a small, named index rather
# than dumping whole files — the builder pulls a bounded head excerpt on request.
DOCTRINE_FILES = {
    "system": Path.home() / "vault/final_master_summary.md",
    "memory": Path.home() / "vault/final_memory_architecture.md",
    "handoff": Path.home() / "vault/final_handoff.md",
}

_DOCTRINE_EXCERPT_CHARS = 4000

# Newest N entries of events.log to render. The event log is retention-bounded by
# TIME (events.retention_hours), not by count, so it grows with the event RATE —
# which means the grounded block is LARGEST exactly when the system is flapping,
# i.e. exactly when the supervisor is being asked what is wrong. Measured
# 2026-07-16 (agentbench #7): the log was 56 entries / 19,901 chars = 44.6% of
# the whole state block, and the block itself was 52% of T1's context window.
#
# Capping the newest N is a bounded projection, not a lie: no FIELD is dropped,
# only old rows of one time-series, and the omission is DISCLOSED in-band so the
# model knows they exist and can ask. Same contract as the doctrine excerpt's
# "…[truncated — ask to see more]".
_EVENT_LOG_MAX = int(os.environ.get("LOKI_SUPERVISOR_EVENT_LOG_MAX", "20"))

# live_state's share of T1's declared context window. The block must leave room
# for the ledger, the action registry, retrieved evidence and the answer itself,
# so it gets a named slice rather than "whatever it happens to be".
#
# This is the coupling that was missing (agentbench #7): the window is declared
# in MONARCH_TIERS["t1"].context_size and NOTHING read it, so the fit was
# arithmetic luck. Now the block is sized against the window it is fed into.
_LIVE_STATE_SHARE = float(os.environ.get("LOKI_SUPERVISOR_STATE_SHARE", "0.35"))
_CHARS_PER_TOKEN = 4          # generous; JSON tokenizes worse, so this errs small


def _live_state_budget() -> int:
    from ..schema import MONARCH_TIERS
    return int(MONARCH_TIERS["t1"].context_size * _CHARS_PER_TOKEN
               * _LIVE_STATE_SHARE)


def load_state_snapshot() -> Optional[dict]:
    """Read-only system state. Returns the SystemModel as a plain dict (the LLM
    context is text, not objects), or None if the daemon has not written state
    yet. Never touches the live store."""
    model = StateStore.load_from_disk()
    if model is None:
        return None
    return json.loads(model.model_dump_json())


def _live_state_block(snap: dict, budget: Optional[int] = None) -> str:
    """Render the state snapshot to fit a declared slice of T1's context window.

    Three budget decisions, in order of how much they cost the model:

    1. **Compact separators.** `indent=2` on a deeply-nested snapshot spends ~30%
       of its bytes on whitespace — 47,649 → 33,482 chars measured — for ZERO
       information loss. The pretty-printing bought nothing and cost a third of
       the block.
    2. **Trim the event log, adaptively.** `events.log` is retention-bounded by
       TIME, not count, so it grows with the event RATE: measured at 44.6% of the
       block, and largest exactly when the system is flapping — i.e. exactly when
       the supervisor is asked what is wrong. It is the only genuinely
       runtime-unbounded series here, so it is the only thing trimmed, newest
       first, and only as far as the budget requires.
    3. **Disclose whatever was dropped.** Same contract as the doctrine excerpt's
       "…[truncated — ask to see more]": the model is told what it is missing so
       it can ask, rather than silently reasoning over a hole.

    Everything else renders whole — every field the supervisor might cite is
    still here. That is deliberate: this block exists to make grounding possible,
    and a projection that drops a field the model needs turns "cite the snapshot"
    into "confabulate the snapshot", which is the failure this file already has a
    scar from (see load_ledger below).

    If even a zero-event block exceeds budget, that is disclosed and logged too —
    an over-budget block that says so beats one that silently overflows T1 and
    gets its grounding truncated away by llama.cpp.
    """
    budget = _live_state_budget() if budget is None else budget

    def render(snapshot: dict) -> str:
        return json.dumps(snapshot, separators=(",", ":"), default=str)

    events = snap.get("events")
    log = events.get("log") if isinstance(events, dict) else None
    total = len(log) if isinstance(log, list) else 0

    shown, note, kept = dict(snap), "", total
    if total:
        # Newest-first ladder: take the largest cap that fits the budget.
        for cap in (total, _EVENT_LOG_MAX, 10, 5, 0):
            if cap > total:
                continue
            trial = dict(snap)
            trimmed = dict(events)
            trimmed["log"] = log[-cap:] if cap else []
            trial["events"] = trimmed
            shown, kept = trial, cap
            if len(render(trial)) <= budget:
                break
        if kept < total:
            note = (f"_showing the newest {kept} of {total} events (older omitted "
                    f"to fit the context budget — ask if you need them). Every "
                    f"other field is complete._\n")

    # The health roster is the OTHER list that grows at runtime (with the number
    # of monitored components). Give it the same bounded-projection treatment as
    # the event log — first N, disclosed — but only once the block is still over
    # budget after the events were trimmed. Events go first (cheapest to lose:
    # old rows of a time series); the roster only if that was not enough.
    health = shown.get("health")
    comps = health.get("components") if isinstance(health, dict) else None
    total_c = len(comps) if isinstance(comps, list) else 0
    if total_c and len(render(shown)) > budget:
        kept_c = total_c
        for cap in (total_c, 20, 10, 5, 0):
            if cap > total_c:
                continue
            trial = dict(shown)
            h = dict(health)
            h["components"] = comps[:cap]
            trial["health"] = h
            shown, kept_c = trial, cap
            if len(render(trial)) <= budget:
                break
        if kept_c < total_c:
            note += (f"_showing {kept_c} of {total_c} health components (rest "
                     f"omitted to fit the context budget — ask if you need them). "
                     f"Every other field is complete._\n")

    blob = render(shown)
    if len(blob) > budget:
        # Last resort: even with both runtime-unbounded lists trimmed, a single
        # oversized field still blows the budget. ENFORCE the window rather than
        # merely disclose it — a bounded block that says it was cut beats one that
        # silently overflows T1 and has its grounding truncated away by llama.cpp.
        # This is the guarantee the headroom benchmark checks: len(block) <= budget
        # for ANY snapshot, not just when the event log happens to be large.
        over = len(blob) - budget
        marker = ("\n…[state truncated to fit the context window — ask for "
                  "specific fields]")
        blob = blob[:max(0, budget - len(marker))] + marker
        logger.warning(
            "[supervisor] live_state block hard-capped to its %d-char budget "
            "(%.0f%% of T1's window); the snapshot outgrew the window by %d chars "
            "even with its lists trimmed",
            budget, 100 * _LIVE_STATE_SHARE, over)
        note += ("_note: the state block was truncated to fit the context window; "
                 "ask for specific fields if you need them._\n")
    return ("## live_state (state.json)\n" + note + "```json\n" + blob + "\n```\n")


def load_ledger() -> List[dict]:
    """Read-only projection of the authority ledger (trust tiers per action).
    Reads authority.json directly; does not instantiate the mutable ledger."""
    if not LEDGER_PATH.exists():
        return []
    try:
        data = json.loads(LEDGER_PATH.read_text())
    except Exception as exc:
        logger.warning("authority.json unreadable (%s)", exc)
        return []
    # authority.json shape: {"actions": {action_id: {...}}, ...} — be tolerant.
    actions = data.get("actions", data) if isinstance(data, dict) else {}
    rows = []
    for aid, rec in actions.items():
        if not isinstance(rec, dict):
            continue
        rows.append({
            "action_id": aid,
            "current_tier": rec.get("current_tier"),
            # authority.py persists these as clean_run_count / state (see
            # ActionRecord.model_dump). The old clean_runs / lifecycle keys
            # never existed on disk, so this grounded block was always null —
            # the supervisor confabulated exactly where it must cite. Read the
            # real keys; keep the legacy names as tolerant fallbacks.
            "clean_runs": rec.get("clean_run_count",
                                  rec.get("clean_runs", rec.get("n", None))),
            "lifecycle": rec.get("state",
                                 rec.get("lifecycle_state", rec.get("lifecycle"))),
        })
    return rows


def registered_actions() -> List[dict]:
    """The only actions the supervisor may propose. Pulled from the live registry
    so the model can never reference a behavior that does not exist."""
    out = []
    for aid, action in ACTIONS.items():
        out.append({
            "action_id": aid,
            "description": getattr(action, "description", ""),
            "default_tier": int(action.default_tier),
            "reversible": getattr(action, "reversible", None),
            "costs_money": getattr(action, "costs_money", None),
            "vram_mb": getattr(action, "vram_mb", None),
            "nonblocking_veto_sec": action.nonblocking_veto_sec,
        })
    return out


def doctrine_excerpt(key: str) -> Optional[str]:
    """Bounded head excerpt of a canonical doctrine file, by index key. Returns
    None if the file is absent. Bounded so a 200KB doctrine file cannot blow the
    context window — the model gets enough to orient and can ask for more."""
    path = DOCTRINE_FILES.get(key)
    if path is None or not path.exists():
        return None
    text = path.read_text(errors="replace")
    if len(text) > _DOCTRINE_EXCERPT_CHARS:
        text = text[:_DOCTRINE_EXCERPT_CHARS] + "\n…[truncated — ask to see more]"
    return text


def _retrieved_block(question: str) -> Optional[str]:
    """Run the deterministic memory-layer retrieval for this question and format it
    as a grounded sub-block. Returns None when there is nothing to add. gather()
    never raises, so a degraded layer becomes a note, never a broken turn."""
    result = retrieval.gather(question)
    if not result.snippets and not result.notes:
        return None
    lines = ["## retrieved_context (memory layers — read fresh this turn; cite each "
             "claim by its [locator])"]
    for s in result.snippets:
        lines.append("\n" + retrieval.format_snippet(s))   # one shared formatter
    if result.notes:
        lines.append("\n_retrieval notes: " + "; ".join(result.notes) + "_")
    return "\n".join(lines) + "\n"


def build_context(question: Optional[str] = None,
                  include_doctrine: Optional[List[str]] = None,
                  retrieve: bool = True) -> str:
    """Assemble the full grounded context block as text for the system turn.

    question: the operator's question. When present (and `retrieve`), it drives
    deterministic query-directed retrieval across the memory layers (§8.6 router),
    injected as `## retrieved_context` — this replaces the old 4 KB doctrine head
    excerpt as the supervisor's path to deep infrastructure knowledge.
    include_doctrine: optional list of DOCTRINE_FILES keys to inline verbatim.
    """
    parts: List[str] = []
    parts.append(CONTEXT_HEADING + " (read fresh from disk this turn)\n"
                 "# Every claim you make about live state must trace to a value below.\n")

    snap = load_state_snapshot()
    if snap is None:
        parts.append("## live_state\n(no state.json on disk yet — the daemon has not "
                     "written state. Say so; do not estimate live values.)\n")
    else:
        parts.append(_live_state_block(snap))

    parts.append("## authority_ledger (authority.json — trust tiers)\n```json\n"
                 + json.dumps(load_ledger(), indent=2, default=str) + "\n```\n")

    parts.append("## registered_actions (the ONLY actions you may propose)\n```json\n"
                 + json.dumps(registered_actions(), indent=2, default=str) + "\n```\n")

    if question and retrieve:
        block = _retrieved_block(question)
        if block is not None:
            parts.append(block)

    for key in (include_doctrine or []):
        excerpt = doctrine_excerpt(key)
        if excerpt is not None:
            parts.append(f"## doctrine::{key} ({DOCTRINE_FILES[key]})\n{excerpt}\n")
        else:
            parts.append(f"## doctrine::{key}\n(not found on disk at "
                         f"{DOCTRINE_FILES.get(key)})\n")

    return "\n".join(parts)
