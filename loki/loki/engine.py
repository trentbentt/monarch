"""
Decision engine — the §12.6 consumer that closes the loop the Phase 2 listeners
opened.

Runs as a daemon thread on its own 10s tick (decoupled from listener cadences —
it acts off StateStore snapshots, not live polls). Each tick:

  1. reload the authority ledger      (pick up CLI promote/demote/approve)
  2. process standing approvals        (execute Tier-3 asks the operator OK'd)
  3. snapshot system state             (read-only; never holds the model lock)
  4. evaluate pure-function rules       → ProposedAction | None
  5. dispatch through the authority gate (cooldown-deduped)
  6. publish the decisions domain       (the engine's ONLY write)

The engine is a pure CONSUMER of domain state. The one domain it writes is
`decisions` (pending asks + a read-only ledger projection), pushed via
store.apply — it never touches tier/resource/health state, preserving the v0.2
single-writer invariant. Mirrors BaseListener error-isolation: a tick that
raises is logged and the loop continues — the engine never dies.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Dict, Optional

from .authority import AuthorityGate, AuthorityLedger
from .rules import RULES
from .state import StateStore
from .timeutil import utcnow as _utcnow   # shared UTC clock (engine + authority)

logger = logging.getLogger(__name__)


class DecisionEngine:
    name = "engine"
    interval_sec = 10.0      # decoupled from listener cadences; acts off snapshots
    cooldown_sec = 60.0      # min seconds before re-proposing the same dedup_key

    def __init__(self) -> None:
        self.store = StateStore.get()
        self.ledger = AuthorityLedger()
        self.ledger.load()
        self.gate = AuthorityGate(self.store, self.ledger)
        self._seen: Dict[str, datetime] = {}   # dedup_key → last proposed
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Supervisor proposal intake — DEFAULT OFF. When LOKI_SUPERVISOR_PROPOSALS
        # is unset, no queue is drained and the engine behaves byte-for-byte as
        # before. The defensive import guarantees a supervisor-side error can never
        # take down the decision loop. See loki/supervisor/ (§9.5 / §12.6): the
        # supervisor is an additional PROPOSAL source, never an additional authority.
        self._supervisor_queue = None
        if os.environ.get("LOKI_SUPERVISOR_PROPOSALS", "").lower() in (
                "1", "true", "yes", "on"):
            try:
                from .supervisor.proposals import SupervisorProposalQueue
                self._supervisor_queue = SupervisorProposalQueue()
                logger.info("[%s] supervisor proposal intake ENABLED", self.name)
            except Exception as exc:
                logger.error("[%s] supervisor intake disabled (import failed): %s",
                             self.name, exc)

    # ── Thread lifecycle (same shape as BaseListener) ──────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"engine-{self.name}", daemon=True,
        )
        self._thread.start()
        logger.info("[%s] started (interval=%.0fs)", self.name, self.interval_sec)

    def stop(self) -> None:
        self._stop_event.set()
        # No ledger flush here. Every trust-counter / token mutation already
        # persisted atomically under the cross-process lock at the moment it
        # happened (AuthorityLedger._locked + _write_unlocked), so in-memory and
        # disk are already in sync. A whole-state save() from the daemon's
        # possibly-stale in-memory view could only CLOBBER a mutation a loki-q CLI
        # process committed since this tick's load() — the exact lost-update the
        # ledger is architected to prevent (review H1).

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Core tick ──────────────────────────────────────────────────────────────
    def tick(self) -> None:
        # 1. reload ledger so CLI mutations (promote/demote/approve) take effect
        self.ledger.load()
        # 1.5 finalize any actions that finished executing off-thread (emit +
        #     record_outcome happen here, on the engine thread → ledger stays
        #     single-writer even though the subprocess ran on a worker thread).
        self.gate.collect_finished()
        # 2. execute any standing Tier-3 asks the operator approved between ticks
        executed = self.gate.process_pending_approvals()
        # 3. read-only snapshot
        snap = self.store.snapshot()
        # 4. evaluate rules → this tick's live proposals, keyed by dedup_key so
        #    distinct units of work (e.g. t3 vs t5 of the same action) never
        #    collapse onto one another.
        proposed_now = {}
        for rule in RULES:
            for p in rule(snap):
                proposed_now[p.dedup_key] = p
        # 4.5 supervisor proposals (DEFAULT OFF). Drained from the file queue and
        #     merged into proposed_now so each is classified, cooldown-deduped, and
        #     operator-gated identically to a rule proposal — no special path, no
        #     standing authority. drain() re-validates every entry against the
        #     ACTIONS registry, so a hallucinated/hand-edited action cannot enter.
        if self._supervisor_queue is not None:
            try:
                for p in self._supervisor_queue.drain():
                    proposed_now[p.dedup_key] = p
            except Exception as exc:
                logger.error("[%s] supervisor drain failed: %s", self.name, exc)
        # 5. GC: drop standing run-asks whose condition has resolved (tier
        #    recovered). Without this, an ask raised before recovery lingers.
        #    Supervisor asks are one-shot (no recurring condition — their condition
        #    is "operator undecided"), so we keep them in the active set until the
        #    gate clears them on approve / veto / veto-window-fire; otherwise they'd
        #    be pruned the tick after they were drained. No-op when intake is off.
        active = set(proposed_now) | {
            k for k, a in self.gate.pending.items() if a.origin != "rule"
        }
        self.gate.prune_stale_runs(active)
        # 5.5 default-proceed non-blocking Tier-3 asks whose veto window elapsed
        #     AND whose condition survived prune (still proposed this tick). Done
        #     after prune so a cleared condition / newly-available higher cascade
        #     rung cancels the pending offload instead of firing it (§10.3).
        executed |= self.gate.fire_expired_nonblocking()
        # 6. dispatch live proposals (deduped + cooldown-gated), per dedup_key
        for dedup_key, proposed in proposed_now.items():
            if dedup_key in executed:
                # Just dispatched this tick; the snapshot may not reflect
                # recovery yet (tier_health lags). Arm cooldown and skip
                # re-asking — prune clears it once the condition clears.
                self._mark(proposed.dedup_key)
                continue
            if dedup_key in self.gate.pending:
                continue                              # already a standing ask
            if self.gate.is_in_flight(dedup_key):
                # Still executing on a worker thread; don't re-dispatch.
                self._mark(proposed.dedup_key)
                continue
            # Cooldown throttles SELF-RE-PROPOSING rules (they re-fire every tick
            # while their condition holds). A supervisor proposal is drained from
            # the queue exactly once and never re-proposed, so cooldown-skipping it
            # would silently drop the operator's explicit request. It is already
            # deduped by the pending/in-flight checks above, so exempting it from
            # cooldown cannot cause a storm — it just guarantees the ask surfaces.
            if proposed.origin == "rule" and self._on_cooldown(proposed.dedup_key):
                continue
            self.gate.dispatch(proposed)
            self._mark(proposed.dedup_key)
        # 7. publish the decisions domain (the engine's only write)
        self._publish_decisions()

    def _on_cooldown(self, key: str) -> bool:
        last = self._seen.get(key)
        if last is None:
            return False
        return (_utcnow() - last).total_seconds() < self.cooldown_sec

    def _mark(self, key: str) -> None:
        self._seen[key] = _utcnow()

    def _publish_decisions(self) -> None:
        """Push pending asks + a read-only ledger projection onto the decisions
        domain via the single writer thread. Deep-copies so the published model
        never shares mutable rows with the live ledger."""
        asks = [a.model_copy(deep=True) for a in self.gate.pending_asks()]
        records = [r.model_copy(deep=True) for r in self.ledger.records_list()]
        now = _utcnow()

        def update(model) -> None:
            model.decisions.pending_asks = asks
            model.decisions.ledger = records
            model.decisions.last_tick = now

        self.store.apply(update)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                logger.error("[%s] tick raised %s: %s",
                             self.name, type(exc).__name__, exc, exc_info=True)
            self._stop_event.wait(self.interval_sec)
