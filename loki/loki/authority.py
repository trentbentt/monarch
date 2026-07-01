"""
Authority gate + durable trust ledger — the §9.5 three-tier authority model.

Two collaborators:

  AuthorityLedger  — owns ~/.local/state/loki/authority.json. Holds the
                     N=12 trust counters per action and the one-shot per-run
                     approvals the operator grants from the CLI. This file is
                     SEPARATE from state.json by design: state.json is
                     non-doctrine (§0.1 rule 5), pruned/rehydrated on cold-start;
                     an action with 11 clean runs must NOT silently reset to 0
                     on a daemon restart, so the counters own their own store
                     with atomic-replace write discipline (mirrors
                     state.py:save_to_disk).

  AuthorityGate    — classifies each ProposedAction into a tier (§9.5.2) and
                     dispatches it: Tier 1 acts silently, Tier 2 acts + logs,
                     Tier 3 surfaces a PendingAsk and waits for operator
                     approval. Records every outcome back to the ledger and,
                     after N=12 clean runs, proposes a promotion ask (never
                     self-promotes — promotion is always a Tier 3 ask).

Doctrine: master_summary §9.5 / §9.5.2 (authority model + N=12 lifecycle),
§12.6 (decision-engine flow).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .actions import ACTIONS
from .schema import (
    ActionLifecycleState,
    ActionRecord,
    ActionTier,
    FLAP_THRESHOLD_24H,
    PendingAsk,
    ProposedAction,
)
from .timeutil import utcnow as _utcnow   # shared UTC clock (engine + authority)

logger = logging.getLogger(__name__)

AUTHORITY_PATH = Path(os.environ.get(
    "LOKI_AUTHORITY_PATH",
    Path.home() / ".local/state/loki/authority.json",
))

PROMOTION_THRESHOLD = 12   # §9.5.2 Item 7 — uniform across all actions
_FLAP_THRESHOLD = FLAP_THRESHOLD_24H   # shared single source (schema.py)


# Seed registry: one cold-start ledger row per registered action. Built from
# ACTIONS so the ledger stays in lockstep with the action contract metadata.
ACTION_REGISTRY: Dict[str, dict] = {
    aid: dict(
        description=a.description,
        current_tier=a.default_tier,
        target_tier=a.target_tier,
    )
    for aid, a in ACTIONS.items()
}


class AuthorityLedger:
    """Durable N=12 counters + one-shot run approvals. Survives daemon restart
    by design — NOT in state.json."""

    def __init__(self) -> None:
        self.records: Dict[str, ActionRecord] = {}
        self.approved_runs: set[str] = set()
        self.vetoed_runs: set[str] = set()   # standing operator vetoes (non-blocking Tier 3)

    # ── Persistence ───────────────────────────────────────────────────────────
    def _hydrate(self) -> bool:
        """Parse authority.json into memory and cold-start-seed any missing
        rows. Returns True if in-memory state diverged from disk (cold start /
        new action / corrupt file) and therefore must be persisted.

        Single read — no TOCTOU. A missing file surfaces as FileNotFoundError
        rather than a check-then-read exists() pair, closing the window where a
        concurrent writer could materialize the file between two probes.
        os.replace() (see _write_unlocked) publishes atomically, so a reader
        never observes a torn file. Caller owns any locking."""
        data: dict = {}
        seeded = False
        try:
            data = json.loads(AUTHORITY_PATH.read_text())
        except FileNotFoundError:
            seeded = True   # missing file → will materialize below
        except Exception as exc:
            logger.error("[authority] failed to parse %s: %s — reseeding",
                         AUTHORITY_PATH, exc)
            data = {}
            seeded = True

        records: Dict[str, ActionRecord] = {}
        for aid, raw in (data.get("actions") or {}).items():
            try:
                records[aid] = ActionRecord.model_validate(raw)
            except Exception as exc:
                logger.error("[authority] dropping unparseable row %s: %s", aid, exc)

        # Seed/hydrate cold-start rows for any registered action missing a row.
        for aid, seed in ACTION_REGISTRY.items():
            if aid not in records:
                logger.info("[authority] seeding cold-start row: %s", aid)
                records[aid] = ActionRecord(
                    action_id=aid,
                    description=seed["description"],
                    current_tier=seed["current_tier"],
                    target_tier=seed["target_tier"],
                    state=ActionLifecycleState.COLD_START,
                )
                seeded = True

        self.records = records
        self.approved_runs = set(data.get("approved_runs") or [])
        self.vetoed_runs = set(data.get("vetoed_runs") or [])
        return seeded

    def load(self) -> None:
        """Hydrate from authority.json, then seed any missing rows from
        ACTION_REGISTRY (cold-start). Idempotent — safe to call every tick to
        pick up CLI mutations (promote/demote/approve).

        Lockless read: os.replace publishes atomically so a steady-state tick
        never sees a torn file. The cold-start materialize takes the write lock
        via _materialize_seed() — an atomic RMW, not a lock-the-write-only."""
        if self._hydrate():
            # Materialize the durable file the moment we seed (first load / new
            # action / corrupt file) so authority.json exists from daemon start
            # and survives an ungraceful kill. Steady-state ticks re-read an
            # existing file → no seeding → no write.
            self._materialize_seed()

    def _materialize_seed(self) -> None:
        """Atomically seed cold-start rows under the advisory flock.

        The lockless _hydrate() in load() detected we need to seed. Re-do that
        read-modify-write UNDER the lock so a mutation another process committed
        in the gap between the lockless read and this write is preserved, not
        clobbered — the lost-update class the per-op mutators already avoid (H1).
        Re-hydrating under the lock picks up that committed write and re-seeds any
        still-missing row; we write only if state is genuinely still divergent."""
        AUTHORITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        lock_path = AUTHORITY_PATH.with_suffix(".lock")
        with open(lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if self._hydrate():        # re-read + re-seed under the lock
                self._write_unlocked()

    @contextmanager
    def _locked(self):
        """Cross-process atomic read-modify-write.

        Holds the advisory flock for the WHOLE re-hydrate→mutate→write cycle, so
        a stale in-memory writer (the daemon between ticks, or a short-lived
        `loki-q` CLI process) can never clobber another process's committed
        mutation. save() alone only serializes the write — it does NOT protect
        the read that precedes the mutation, which is where the lost-update and
        double-consume races lived. Mutators call _write_unlocked() inside this
        block when (and only when) they actually change state."""
        AUTHORITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        lock_path = AUTHORITY_PATH.with_suffix(".lock")
        with open(lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            self._hydrate()
            yield

    def _write_unlocked(self) -> None:
        """Serialize current state via a unique temp + atomic os.replace.
        Caller MUST already hold the advisory flock (via _locked() or save())."""
        AUTHORITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "actions": {aid: r.model_dump(mode="json") for aid, r in self.records.items()},
            "approved_runs": sorted(self.approved_runs),
            "vetoed_runs": sorted(self.vetoed_runs),
            "saved_at": _utcnow().isoformat(),
        }
        blob = json.dumps(payload, indent=2, default=str)
        # Unique per-write temp so concurrent writers can't clobber the same
        # scratch file; os.replace stays atomic on the rename.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(AUTHORITY_PATH.parent), prefix=".authority-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, AUTHORITY_PATH)
            # fsync the PARENT DIR so the rename itself is durable on power loss —
            # the data fsync above only persists the file contents, not the
            # directory entry that now points at them (review C5).
            dir_fd = os.open(str(AUTHORITY_PATH.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def save(self) -> None:
        """Persist the current in-memory state atomically under the advisory
        flock — a plain write primitive (it does NOT re-read, so it preserves the
        caller's in-memory mutation). Whole-state read-modify-writes that must not
        clobber a concurrent process go through _locked() (per-op mutators) or
        _materialize_seed() (cold-start); the one-shot tokens/trust counters use
        _locked() so the lock is held across their preceding read.

        Cross-process write safety: the daemon and the CLI (loki-q
        promote/approve/demote) write this file from SEPARATE processes. Serialize
        writers with the advisory lock; stage through a unique per-write temp;
        os.replace publishes atomically."""
        AUTHORITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        lock_path = AUTHORITY_PATH.with_suffix(".lock")
        with open(lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            self._write_unlocked()

    # ── Accessors ───────────────────────────────────────────────────────────
    def get(self, action_id: str) -> Optional[ActionRecord]:
        return self.records.get(action_id)

    def records_list(self) -> List[ActionRecord]:
        return list(self.records.values())

    # ── Trust-counter mutations ─────────────────────────────────────────────
    def record(self, action_id: str, outcome: str) -> None:
        """Record an action outcome. ok → clean streak++; failed → streak reset
        (but no demotion — a failed restart isn't operator regret); regretted →
        demote to Tier 3 + reset (operator pressed the regret button).

        Runs the read-modify-write under the cross-process lock so a daemon
        outcome-record can't clobber a concurrent CLI promote/demote (or vice
        versa) — same lost-update class as the one-shot tokens."""
        with self._locked():
            row = self.records.get(action_id)
            if row is None:
                logger.error("[authority] record() for unknown action %s", action_id)
                return
            row.total_runs += 1
            row.last_fired = _utcnow()
            row.last_outcome = outcome
            if outcome == "ok":
                row.clean_run_count += 1
            elif outcome == "regretted":
                row.current_tier = ActionTier.TIER_3
                row.state = ActionLifecycleState.DEMOTED
                row.clean_run_count = 0
                row.demotion_reason = "operator regret (recorded outcome)"
            else:  # "failed" — breaks the clean streak, no tier change
                row.clean_run_count = 0
            self._write_unlocked()

    def mark_eligible_if_ready(self, action_id: str, threshold: int) -> bool:
        """Atomically flip an action to ELIGIBLE under the cross-process lock,
        re-checking the promotion gate against freshly-hydrated state. Returns
        True iff this call performed the flip.

        Must be atomic for the same reason record() is: the daemon evaluates
        eligibility right after record() releases its lock, and a concurrent
        `loki-q` approve/demote can land in that window. Doing the re-check +
        write inside _locked() (which re-hydrates first) means a stale daemon
        snapshot can never clobber the CLI's committed mutation — the exact
        lost-update class this module exists to prevent. The previous code did
        the mutate here but persisted via save(), which does NOT re-hydrate."""
        with self._locked():
            row = self.records.get(action_id)
            if row is None:
                return False
            can_climb = row.current_tier > row.target_tier  # lower int = higher authority
            if (can_climb
                    and row.clean_run_count >= threshold
                    and row.state != ActionLifecycleState.ELIGIBLE):
                row.state = ActionLifecycleState.ELIGIBLE
                self._write_unlocked()
                return True
        return False

    def approve_run(self, action_id: str) -> None:
        """Operator grants a one-shot approval for the next Tier-3 run."""
        with self._locked():
            if action_id in self.records:
                self.approved_runs.add(action_id)
                self._write_unlocked()

    def consume_run_approval(self, action_id: str) -> bool:
        """Atomically consume a standing run approval. True if one was present.
        The check-and-discard runs under the cross-process lock against freshly
        re-hydrated state, so a one-shot token is consumed exactly once even if
        the daemon and CLI race for it."""
        with self._locked():
            if action_id in self.approved_runs:
                self.approved_runs.discard(action_id)
                self._write_unlocked()
                return True
        return False

    def veto_run(self, action_id: str) -> None:
        """Operator vetoes the next pending run of a non-blocking Tier-3 action,
        cancelling it before its veto window elapses (§9.5.1 / §10.3)."""
        with self._locked():
            if action_id in self.records:
                self.vetoed_runs.add(action_id)
                self._write_unlocked()

    def consume_veto(self, action_id: str) -> bool:
        """Atomically consume a standing veto. True if one was present."""
        with self._locked():
            if action_id in self.vetoed_runs:
                self.vetoed_runs.discard(action_id)
                self._write_unlocked()
                return True
        return False

    def promote(self, action_id: str) -> bool:
        """Operator approves an ELIGIBLE action's promotion → move to target
        tier (capped). Resets the clean-run streak for the new tier. Returns
        True if a promotion happened."""
        with self._locked():
            row = self.records.get(action_id)
            if row is None:
                return False
            if row.state != ActionLifecycleState.ELIGIBLE:
                return False
            if row.current_tier <= row.target_tier:
                # already at/above cap (lower int = higher authority); nothing to do
                return False
            row.current_tier = row.target_tier
            row.state = ActionLifecycleState.PROMOTED
            row.clean_run_count = 0
            row.demotion_reason = None
            self._write_unlocked()
            return True

    def demote(self, action_id: str, reason: str) -> bool:
        """Operator regret: reset to Tier 3, zero the streak, drop any pending
        run approval."""
        with self._locked():
            row = self.records.get(action_id)
            if row is None:
                return False
            row.current_tier = ActionTier.TIER_3
            row.state = ActionLifecycleState.DEMOTED
            row.clean_run_count = 0
            row.demotion_reason = reason
            self.approved_runs.discard(action_id)
            self._write_unlocked()
            return True


class AuthorityGate:
    """Classifies and dispatches proposed actions; records outcomes; proposes
    promotions at N=12. Holds the standing PendingAsk set in memory; the engine
    publishes it to the decisions domain each tick."""

    def __init__(self, store, ledger: AuthorityLedger) -> None:
        self.store = store
        self.ledger = ledger
        self.pending: Dict[str, PendingAsk] = {}   # dedup_key → standing ask
        # Off-thread action execution: a long subprocess must never freeze the
        # decision loop. Workers run the action only; emit + ledger record are
        # finalized on the engine thread via collect_finished().
        self._exec_lock = threading.Lock()
        self._in_flight: Dict[str, bool] = {}      # dedup_key → currently executing
        self._finished: List[tuple] = []           # (proposed, emit_kind, outcome) to finalize
        # The ELIGIBLE flag is durable (authority.json) but the PendingAsk is
        # in-memory only. Rebuild standing promotion asks at construction so a
        # daemon restart between eligibility and operator approval never strands
        # an action ELIGIBLE-forever with nothing surfaced.
        self._resurface_promotion_asks()

    def _resurface_promotion_asks(self) -> None:
        """Re-create in-memory promotion asks for any action the ledger already
        holds in ELIGIBLE state. Without this, after a restart the action stays
        ELIGIBLE on disk but _maybe_propose_promotion never re-fires (its guard
        sees state already == ELIGIBLE), so the operator is never re-prompted.

        The ledger is already hydrated before the gate is constructed
        (engine.py loads it first), so we read current records directly — calling
        load() here would re-hydrate from disk and clobber any not-yet-persisted
        in-memory state."""
        for row in self.ledger.records_list():
            if row.state == ActionLifecycleState.ELIGIBLE:
                self.pending[f"{row.action_id}:promotion"] = PendingAsk(
                    action_id=row.action_id, params={},
                    rationale=(f"{row.action_id}: {row.clean_run_count} clean runs at "
                               f"Tier {int(row.current_tier)} — propose promotion to "
                               f"Tier {int(row.target_tier)}"),
                    proposed_at=_utcnow(),
                    tier=row.current_tier, kind="promotion", blocking=True,
                )

    # ── Classification ──────────────────────────────────────────────────────
    def classify(self, proposed: ProposedAction) -> ActionTier:
        """Current tier comes from the ledger. Flapping guard forces Tier 3:
        even a promoted action will not auto-fire against a tier that is
        restart-looping — surface it to the operator instead.

        Origin floor (§9.5): a non-rule proposer (the supervisor LLM) NEVER
        inherits the autonomy a deterministic rule earned. Whatever tier the
        ledger row sits at, an LLM-origin proposal is floored to Tier 3 so it
        always surfaces for explicit operator approval — the supervisor is a
        proposal source, never an authority."""
        if proposed.origin != "rule":
            return ActionTier.TIER_3
        row = self.ledger.get(proposed.action_id)
        tier = row.current_tier if row else ActionTier.TIER_3
        if self._is_flapping(proposed):
            return ActionTier.TIER_3
        return tier

    def _is_flapping(self, proposed: ProposedAction) -> bool:
        tid = proposed.params.get("tier")
        if not tid:
            return False
        try:
            snap = self.store.snapshot()
            t = snap.tiers.get(tid)
            return bool(t and t.runtime.restart_count_24h >= _FLAP_THRESHOLD)
        except Exception:
            return False

    # ── Dispatch ──────────────────────────────────────────────────────────────
    def dispatch(self, proposed: ProposedAction) -> None:
        tier = self.classify(proposed)
        if tier == ActionTier.TIER_1:
            self._spawn_exec(proposed, emit_kind="silent")
        elif tier == ActionTier.TIER_2:
            self._spawn_exec(proposed, emit_kind="tier2")
        else:  # TIER_3 — surface and ask, unless the operator pre-approved
            if self.ledger.consume_run_approval(proposed.action_id):
                self.pending.pop(proposed.dedup_key, None)
                self._spawn_exec(proposed, emit_kind="approved")
            else:
                # §9.5.1: actions may declare a non-blocking veto window. If set,
                # the ask carries a deadline and DEFAULT-PROCEEDS at timeout
                # (process_pending_approvals fires it) unless the operator vetoes;
                # else it's a classic blocking ask that waits for explicit approval.
                # Origin floor: a non-rule (LLM) proposal is ALWAYS blocking — the
                # supervisor can never trigger a default-proceed; it waits for the
                # operator to explicitly approve, even for an action whose rule path
                # carries a veto window.
                action = ACTIONS.get(proposed.action_id)
                veto_sec = getattr(action, "nonblocking_veto_sec", None) if action else None
                if proposed.origin != "rule":
                    veto_sec = None
                expires = (_utcnow() + timedelta(seconds=veto_sec)) if veto_sec else None
                self.pending[proposed.dedup_key] = PendingAsk(
                    action_id=proposed.action_id,
                    params=proposed.params,
                    rationale=proposed.rationale,
                    proposed_at=proposed.proposed_at,
                    tier=ActionTier.TIER_3,
                    kind="run",
                    blocking=(veto_sec is None),
                    expires_at=expires,
                    origin=proposed.origin,
                )
                if veto_sec:
                    self.store.emit(
                        type="action_veto_window_open", severity="warning",
                        detail=(f"{proposed.rationale} — proceeding in {veto_sec}s unless "
                                f"vetoed (loki-q authority veto {proposed.action_id})"),
                        action_id=proposed.action_id,
                    )

    def process_pending_approvals(self) -> set[str]:
        """Called every engine tick (even on cooldown). Executes any standing
        run-ask the operator approved between ticks, and clears promotion asks
        the operator has acted on. Returns the set of dedup_keys handled this
        tick so the engine can arm their cooldown and skip same-tick re-asking
        off a not-yet-refreshed snapshot. Keyed by dedup_key; ledger lookups use
        ask.action_id (trust is per action, not per tier)."""
        executed: set[str] = set()
        for key, ask in list(self.pending.items()):
            if ask.kind == "run":
                # Operator veto cancels this run (non-blocking asks carry a veto
                # window; blocking asks just never get approved / are pruned when
                # their condition clears).
                if self.ledger.consume_veto(ask.action_id):
                    del self.pending[key]
                    self.store.emit(
                        type="action_vetoed", severity="info",
                        detail=f"{ask.action_id} vetoed by operator — not run",
                        action_id=ask.action_id,
                    )
                    continue
                if self.ledger.consume_run_approval(ask.action_id):
                    proposed = ProposedAction(
                        action_id=ask.action_id, trigger="operator_approval",
                        params=ask.params, dedup_key=key,
                        rationale=ask.rationale, proposed_at=ask.proposed_at,
                        origin=ask.origin,
                    )
                    self._execute_approved(proposed)
                    executed.add(key)
                    continue
                # Non-blocking Tier-3 default-proceed is handled in
                # fire_expired_nonblocking(), called AFTER the engine prunes asks
                # whose condition cleared this tick — so a veto window the rule
                # stopped re-proposing (pressure relieved, or a higher cascade rung
                # became reclaimable) is cancelled rather than fired.
            elif ask.kind == "promotion":
                row = self.ledger.get(ask.action_id)
                if row and row.state == ActionLifecycleState.PROMOTED:
                    del self.pending[key]   # operator approved the promotion
                    self.store.emit(
                        type="action", severity="info",
                        detail=f"{ask.action_id} promoted to Tier {int(row.current_tier)}",
                        action_id=ask.action_id,
                    )
        return executed

    def fire_expired_nonblocking(self) -> set[str]:
        """Default-proceed any non-blocking Tier-3 ask whose veto window elapsed.
        MUST be called AFTER prune_stale_runs in the engine tick: an ask whose
        condition cleared this tick (rule stopped proposing it — pressure relieved
        or a higher cascade rung became reclaimable, §10.3) is pruned first, so
        only asks whose condition still holds reach their deadline and fire. The
        operator's veto is checked earlier each tick (process_pending_approvals),
        so a veto always wins over the deadline. Returns the fired dedup_keys."""
        fired: set[str] = set()
        now = _utcnow()
        for key, ask in list(self.pending.items()):
            if (ask.kind == "run" and not ask.blocking
                    and ask.expires_at is not None and now >= ask.expires_at):
                proposed = ProposedAction(
                    action_id=ask.action_id, trigger="veto_window_elapsed",
                    params=ask.params, dedup_key=key,
                    rationale=ask.rationale, proposed_at=ask.proposed_at,
                    origin=ask.origin,
                )
                self._execute_approved(proposed)
                fired.add(key)
        return fired

    def prune_stale_runs(self, active_dedup_keys: set[str]) -> None:
        """Drop run-asks whose triggering condition no longer holds (the tier
        recovered — via this engine's restart or on its own). Promotion asks are
        not condition-driven and are never pruned here. Keyed by dedup_key so a
        still-crashed t3 cannot keep a recovered t5's ask alive (or vice-versa)."""
        for key, ask in list(self.pending.items()):
            if ask.kind == "run" and key not in active_dedup_keys:
                logger.info("[authority] pruning stale run-ask %s (condition cleared)", key)
                del self.pending[key]

    def _execute_approved(self, proposed: ProposedAction) -> None:
        # Clear the standing run ask, then run OFF the engine thread — the
        # subprocess can take minutes. collect_finished() finalizes (emit +
        # record_outcome) back on the engine thread when the worker returns.
        self.pending.pop(proposed.dedup_key, None)
        self._spawn_exec(proposed, emit_kind="approved")

    # ── Off-thread execution ────────────────────────────────────────────────
    def _spawn_exec(self, proposed: ProposedAction, emit_kind: str) -> None:
        """Run an action on a short-lived worker thread so a multi-minute
        subprocess never freezes the decision loop. The worker ONLY runs the
        action; emit + ledger record happen on the engine thread via
        collect_finished(), keeping ledger access single-threaded."""
        key = proposed.dedup_key
        with self._exec_lock:
            if key in self._in_flight:
                return                            # already running — never double-run
            self._in_flight[key] = True

        def _worker() -> None:
            # A raising execute()/matches() must NOT leave the dedup key stuck in
            # _in_flight — that would wedge the action forever (is_in_flight stays
            # True, so it can never be re-dispatched). Treat any crash as a failed
            # outcome and always release the slot + enqueue the result.
            outcome = "failed"
            try:
                outcome = self._act(proposed)
            except Exception:
                logger.exception(
                    "[authority] action %s crashed in worker thread",
                    proposed.action_id)
            finally:
                with self._exec_lock:
                    self._in_flight.pop(key, None)
                    self._finished.append((proposed, emit_kind, outcome))

        threading.Thread(target=_worker, name=f"action-{key}", daemon=True).start()

    def collect_finished(self) -> None:
        """Finalize actions that finished executing off-thread: emit the
        tier-appropriate event and record the outcome. MUST run on the engine
        thread (it touches the ledger). Called once at the top of each tick."""
        with self._exec_lock:
            done = self._finished
            self._finished = []
        for proposed, emit_kind, outcome in done:
            if emit_kind == "tier2":
                self.store.emit(
                    type="action", severity="info",
                    tier=proposed.params.get("tier"),
                    detail=f"{proposed.rationale} (Tier 2 autonomous-with-log)",
                    action_id=proposed.action_id, outcome=outcome,
                )
            elif emit_kind == "approved":
                self.store.emit(
                    type="action", severity="info",
                    tier=proposed.params.get("tier"),
                    detail=f"{proposed.rationale} (operator-approved Tier 3 run)",
                    action_id=proposed.action_id, outcome=outcome,
                )
            # emit_kind == "silent" (Tier 1): autonomous, no event by design
            #
            # Trust isolation (§9.5): only deterministic-rule outcomes move the
            # N=12 ladder. A supervisor (non-rule) run is an operator-approved
            # one-off — it must not earn promotion trust, and a failed LLM-origin
            # run (e.g. bad params) must not reset the clean streak a rule earned.
            # The event above still records it for operator visibility.
            if proposed.origin == "rule":
                self.record_outcome(proposed.action_id, outcome)

    def is_in_flight(self, dedup_key: str) -> bool:
        with self._exec_lock:
            return dedup_key in self._in_flight

    def _act(self, proposed: ProposedAction) -> str:
        action = ACTIONS.get(proposed.action_id)
        if action is None:
            logger.error("[authority] no executor for %s", proposed.action_id)
            return "failed"
        if not action.matches(proposed.params):
            logger.error("[authority] params %r rejected by %s.matches()",
                         proposed.params, proposed.action_id)
            return "failed"
        return action.execute(proposed.params)

    # ── Outcome recording + promotion ladder ───────────────────────────────────
    def record_outcome(self, action_id: str, outcome: str) -> None:
        self.ledger.record(action_id, outcome)
        if outcome == "ok":
            self._maybe_propose_promotion(action_id)

    def _maybe_propose_promotion(self, action_id: str) -> None:
        """After N=12 clean runs below the target tier, surface a promotion ask.
        The engine NEVER self-promotes — the operator approves via the CLI.

        The ELIGIBLE flip is performed atomically by the ledger (re-hydrate +
        write under one lock) so a concurrent CLI mutation is never clobbered;
        the PendingAsk + event are derived only after the durable flip lands."""
        if not self.ledger.mark_eligible_if_ready(action_id, PROMOTION_THRESHOLD):
            return
        row = self.ledger.get(action_id)
        if row is None:   # demoted out from under us between flip and read
            return
        self.pending[f"{action_id}:promotion"] = PendingAsk(
            action_id=action_id, params={},
            rationale=(f"{action_id}: {row.clean_run_count} clean runs at "
                       f"Tier {int(row.current_tier)} — propose promotion to "
                       f"Tier {int(row.target_tier)}"),
            proposed_at=_utcnow(),
            tier=row.current_tier, kind="promotion", blocking=True,
        )
        self.store.emit(
            type="action_promotion_eligible", severity="info",
            detail=(f"{action_id} eligible for promotion to Tier "
                    f"{int(row.target_tier)} after {row.clean_run_count} clean runs"),
            action_id=action_id,
        )

    def demote(self, action_id: str, reason: str) -> bool:
        ok = self.ledger.demote(action_id, reason)
        if ok:
            # pending is keyed by dedup_key; drop every ask for this action
            # (run asks for any tier + the promotion ask).
            for k in [k for k, a in self.pending.items() if a.action_id == action_id]:
                self.pending.pop(k, None)
            self.store.emit(
                type="action_demoted", severity="warning",
                detail=f"{action_id} demoted to Tier 3: {reason}",
                action_id=action_id,
            )
        return ok

    def pending_asks(self) -> List[PendingAsk]:
        return list(self.pending.values())
