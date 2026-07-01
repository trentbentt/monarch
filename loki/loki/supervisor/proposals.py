"""
Supervisor proposal queue — the ONLY write path the supervisor layer has, and it
writes *requests*, never actions.

Design invariant (why this is safe): the supervisor never touches state.json or
authority.json and never calls Action.execute(). When it wants something done it
appends a proposal request to its own queue file. The decision engine drains that
queue on its tick (behind a default-off flag) and feeds each request through the
SAME AuthorityGate a deterministic rule's proposal goes through — so a supervisor
proposal is classified, cooldown-deduped, and operator-gated identically to a rule
proposal. The supervisor gets no special path and no standing authority.

Two layers of hallucination defense:
  • submit() rejects any action_id not in the ACTIONS registry (raises) — the
    supervisor cannot enqueue a behavior that does not exist.
  • drain() re-validates and drops unknown ids (logs) — even a hand-edited or
    corrupt queue file cannot inject a phantom action into the engine.

Doctrine: master_summary §9.5 (authority model) / §12.6 (decision-engine flow).
The queue is a non-doctrine runtime artifact (§0.1 rule 5): atomic-replace writes,
safe to delete (a lost queue loses at most pending proposals, never trust state).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional

from ..actions import ACTIONS
from ..schema import ProposedAction

logger = logging.getLogger(__name__)

QUEUE_PATH = Path(os.environ.get(
    "LOKI_SUPERVISOR_QUEUE",
    Path.home() / ".local/state/loki/supervisor_proposals.json",
))

# Marks every proposal that originated from the supervisor, so the engine, the
# ledger, and the operator can always tell rule-origin from supervisor-origin.
SUPERVISOR_SOURCE = "supervisor"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SupervisorProposalQueue:
    """File-backed request queue. Single producer (the supervisor CLI/agent),
    single consumer (the engine tick). Not high-throughput by design — proposals
    are rare, operator-facing events."""

    def __init__(self, path: Path = QUEUE_PATH) -> None:
        self.path = Path(path)

    # ── producer side (supervisor) ─────────────────────────────────────────────
    def submit(self, action_id: str, rationale: str,
               params: Optional[dict] = None) -> ProposedAction:
        """Enqueue a proposal request for a REGISTERED action. Raises ValueError
        for an unknown action_id — the supervisor cannot invent behaviors."""
        if action_id not in ACTIONS:
            raise ValueError(
                f"unknown action_id {action_id!r}; registered actions: "
                f"{sorted(ACTIONS)}"
            )
        proposal = ProposedAction(
            action_id=action_id,
            trigger=f"{SUPERVISOR_SOURCE}:operator_review",
            params=params or {},
            # dedup_key namespaced so a supervisor proposal never collides with a
            # rule's dedup_key for the same action; the gate's cooldown/dedup then
            # treats them as distinct units of work.
            dedup_key=f"{SUPERVISOR_SOURCE}:{action_id}",
            rationale=rationale.strip(),
            proposed_at=_utcnow(),
            # Provenance the gate enforces on: a non-rule origin is floored to a
            # blocking Tier-3 ask and kept out of the N=12 trust ladder. The
            # supervisor is a proposal source, never an authority (§9.5).
            origin=SUPERVISOR_SOURCE,
        )
        self._append(proposal)
        logger.info("supervisor proposal enqueued: %s — %s", action_id, rationale)
        return proposal

    # ── consumer side (engine) ──────────────────────────────────────────────────
    def drain(self) -> List[ProposedAction]:
        """Return all queued proposals and clear the queue atomically. Re-validates
        each entry against ACTIONS (defense in depth) and silently drops unknowns.
        Never raises into the engine tick — a corrupt queue yields []."""
        # Read+clear under the cross-process lock so a concurrent CLI submit()
        # cannot interleave between the read and the clear — otherwise a proposal
        # appended in that window would be lost, or an already-drained one replayed
        # (double execution). Same advisory-lock discipline as authority.py.
        with self._locked():
            raw = self._read_raw()
            if not raw:
                return []
            # Clear first so a crash mid-dispatch cannot replay proposals next tick.
            self._clear()
        out: List[ProposedAction] = []
        for entry in raw:
            try:
                proposal = ProposedAction.model_validate(entry)
            except Exception as exc:
                logger.warning("dropping malformed supervisor proposal: %s", exc)
                continue
            if proposal.action_id not in ACTIONS:
                logger.warning("dropping supervisor proposal for unknown action %r",
                               proposal.action_id)
                continue
            # Provenance is intrinsic to THIS queue: anything drained here is
            # supervisor-origin by definition. Force it (defense in depth) so a
            # hand-edited/forged entry that omitted or faked `origin` cannot slip
            # through as a rule and escape the Tier-3 floor + trust isolation.
            proposal.origin = SUPERVISOR_SOURCE
            out.append(proposal)
        return out

    def pending(self) -> List[dict]:
        """Read-only peek for the CLI; does not clear."""
        return self._read_raw()

    # ── file plumbing (atomic-replace, mirrors state.py discipline) ─────────────
    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Cross-process advisory lock (mirrors authority.py). Serializes the
        producer (CLI submit) and consumer (engine drain) so the non-atomic
        read-modify-write / read-clear sequences cannot interleave across
        processes. Held only for the file touch — never across a model call."""
        lock_path = self.path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield

    def _read_raw(self) -> List[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("supervisor queue unreadable (%s); treating as empty", exc)
            return []

    def _append(self, proposal: ProposedAction) -> None:
        # Read-modify-write under the lock so a concurrent drain() cannot clear
        # the queue between our read and our write (which would resurrect the
        # just-drained entries) and so two CLI submits cannot clobber each other.
        with self._locked():
            current = self._read_raw()
            current.append(json.loads(proposal.model_dump_json()))
            self._atomic_write(current)

    def _clear(self) -> None:
        self._atomic_write([])

    def _atomic_write(self, data: list) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh, indent=2, default=str)
            os.replace(tmp, self.path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
