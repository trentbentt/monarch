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

# Canonical doctrine the supervisor may cite. Kept as a small, named index rather
# than dumping whole files — the builder pulls a bounded head excerpt on request.
DOCTRINE_FILES = {
    "system": Path.home() / "vault/final_master_summary.md",
    "memory": Path.home() / "vault/final_memory_architecture.md",
    "handoff": Path.home() / "vault/final_handoff.md",
}

_DOCTRINE_EXCERPT_CHARS = 4000


def load_state_snapshot() -> Optional[dict]:
    """Read-only system state. Returns the SystemModel as a plain dict (the LLM
    context is text, not objects), or None if the daemon has not written state
    yet. Never touches the live store."""
    model = StateStore.load_from_disk()
    if model is None:
        return None
    return json.loads(model.model_dump_json())


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
    parts.append("# GROUNDED CONTEXT (read fresh from disk this turn)\n"
                 "# Every claim you make about live state must trace to a value below.\n")

    snap = load_state_snapshot()
    if snap is None:
        parts.append("## live_state\n(no state.json on disk yet — the daemon has not "
                     "written state. Say so; do not estimate live values.)\n")
    else:
        parts.append("## live_state (state.json)\n```json\n"
                     + json.dumps(snap, indent=2, default=str) + "\n```\n")

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
