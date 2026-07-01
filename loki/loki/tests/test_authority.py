"""Concurrency tests for the AuthorityLedger read-modify-write path.

The ledger is written from two SEPARATE processes — the long-lived daemon
(every mutating tick) and the short-lived `loki-q` CLI (promote/approve/demote).
Each process holds its own in-memory view. The original review flagged two HIGH
races (§9.5 authority model):

  * load() TOCTOU — double AUTHORITY_PATH.exists()
  * non-atomic check-then-act in consume_run_approval()/approve_run()

`save()` already serializes the WRITE with an advisory flock, but the
read-modify-write CYCLE is unprotected: a stale in-memory writer clobbers a
concurrent process's committed mutation (lost update). These tests model each
process as its own AuthorityLedger instance sharing one file — a deterministic
stand-in for two processes' in-memory views.
"""

import pytest

from loki import authority
from loki.schema import ActionLifecycleState, ActionTier


@pytest.fixture
def ledger_path(tmp_path, monkeypatch):
    p = tmp_path / "authority.json"
    monkeypatch.setattr(authority, "AUTHORITY_PATH", p)
    return p


def _process_view():
    """A fresh AuthorityLedger that has loaded current on-disk state —
    equivalent to one process constructing + hydrating the ledger."""
    led = authority.AuthorityLedger()
    led.load()
    return led


def test_concurrent_approvals_do_not_lose_updates(ledger_path):
    """CLI grants one approval, daemon grants another from a stale view.
    Both committed approvals must survive — no lost update."""
    daemon = _process_view()
    cli = _process_view()  # both see empty approved_runs

    cli.approve_run("offload_t1_reasoning")          # CLI commits first
    daemon.approve_run("restore_t1_reasoning")       # daemon commits from stale view

    disk = _process_view()
    assert disk.approved_runs == {
        "offload_t1_reasoning",
        "restore_t1_reasoning",
    }


def test_consume_run_approval_is_atomic_across_processes(ledger_path):
    """A one-shot approval must be consumed exactly once even when two
    processes race to consume the same token."""
    seed = _process_view()
    seed.approve_run("offload_t1_reasoning")

    a = _process_view()
    b = _process_view()  # both load the standing approval

    first = a.consume_run_approval("offload_t1_reasoning")
    second = b.consume_run_approval("offload_t1_reasoning")  # stale view

    assert first is True
    assert second is False, "approval was double-consumed across processes"


def test_concurrent_vetoes_do_not_lose_updates(ledger_path):
    """Veto tokens share the consume_run_approval race class; a stale writer
    must not drop a concurrently committed veto."""
    daemon = _process_view()
    cli = _process_view()

    cli.veto_run("offload_t1_reasoning")
    daemon.veto_run("restore_t1_reasoning")

    disk = _process_view()
    assert disk.vetoed_runs == {
        "offload_t1_reasoning",
        "restore_t1_reasoning",
    }


def test_record_outcome_does_not_lose_concurrent_update(ledger_path):
    """Trust-counter mutations share the same lost-update class: a daemon
    record() must not clobber a concurrently committed counter on another
    action."""
    a = _process_view()
    b = _process_view()  # both load fresh, total_runs == 0 everywhere

    a.record("offload_t1_reasoning", "ok")
    b.record("restore_t1_reasoning", "ok")  # stale view of offload's counter

    disk = _process_view()
    assert disk.records["offload_t1_reasoning"].total_runs == 1
    assert disk.records["restore_t1_reasoning"].total_runs == 1


def test_demote_does_not_lose_concurrent_update(ledger_path):
    """A CLI demote of one action must not be clobbered by a concurrent demote
    of another from a stale view."""
    a = _process_view()
    b = _process_view()

    a.demote("offload_t1_reasoning", "operator regret")
    b.demote("restore_t1_reasoning", "operator regret")  # stale view

    disk = _process_view()
    assert disk.records["offload_t1_reasoning"].state == ActionLifecycleState.DEMOTED
    assert disk.records["restore_t1_reasoning"].state == ActionLifecycleState.DEMOTED


def test_promote_does_not_lose_concurrent_update(ledger_path):
    """Two eligible actions promoted concurrently from stale views must both
    land PROMOTED on disk."""
    seed = _process_view()
    for aid in ("offload_t1_reasoning", "restore_t1_reasoning"):
        row = seed.records[aid]
        row.state = ActionLifecycleState.ELIGIBLE
        row.current_tier = ActionTier.TIER_3
        row.target_tier = ActionTier.TIER_2
    seed.save()

    a = _process_view()
    b = _process_view()  # both see two ELIGIBLE rows

    assert a.promote("offload_t1_reasoning") is True
    assert b.promote("restore_t1_reasoning") is True  # stale view

    disk = _process_view()
    assert disk.records["offload_t1_reasoning"].state == ActionLifecycleState.PROMOTED
    assert disk.records["restore_t1_reasoning"].state == ActionLifecycleState.PROMOTED


# ── Promotion-eligibility RMW + restart resurface (review HIGH findings) ──────

class _FakeStore:
    def __init__(self):
        self.events = []

    def emit(self, **kwargs):
        self.events.append(kwargs)


def _seed_eligible_ready(led, aid, *, clean):
    """Force one action to the brink of promotion — clean runs accrued at a
    tier above its target — and persist it."""
    row = led.records[aid]
    row.current_tier = ActionTier.TIER_2
    row.target_tier = ActionTier.TIER_1
    row.clean_run_count = clean
    row.state = ActionLifecycleState.COLD_START
    led.save()


def test_mark_eligible_if_ready_flips_and_is_idempotent(ledger_path):
    aid = "offload_t1_reasoning"
    _seed_eligible_ready(_process_view(), aid, clean=authority.PROMOTION_THRESHOLD)

    assert _process_view().mark_eligible_if_ready(aid, authority.PROMOTION_THRESHOLD) is True
    assert _process_view().records[aid].state == ActionLifecycleState.ELIGIBLE
    # Already eligible → no second flip.
    assert _process_view().mark_eligible_if_ready(aid, authority.PROMOTION_THRESHOLD) is False


def test_mark_eligible_does_not_clobber_concurrent_demote(ledger_path):
    """The daemon evaluates promotion from a stale view while the CLI demotes
    the same action. mark_eligible_if_ready must re-hydrate under the lock and
    refuse to resurrect the pre-demote snapshot (the lost-update class this
    module exists to prevent — previously the path used save(), which does not
    re-hydrate)."""
    aid = "offload_t1_reasoning"
    _seed_eligible_ready(_process_view(), aid, clean=authority.PROMOTION_THRESHOLD)

    daemon = _process_view()   # stale: clean>=threshold, tier above target
    cli = _process_view()
    assert cli.demote(aid, "operator regret") is True   # CLI commits the demote

    flipped = daemon.mark_eligible_if_ready(aid, authority.PROMOTION_THRESHOLD)

    disk = _process_view()
    assert flipped is False, "stale daemon flipped ELIGIBLE over a committed demote"
    assert disk.records[aid].state == ActionLifecycleState.DEMOTED
    assert disk.records[aid].current_tier == ActionTier.TIER_3
    assert disk.records[aid].clean_run_count == 0


def test_eligible_ask_resurfaces_after_restart(ledger_path):
    """An action left ELIGIBLE on disk must regain its standing promotion ask
    when a fresh gate is constructed (daemon restart). The durable flag alone
    is insufficient — _maybe_propose_promotion won't re-fire once state is
    already ELIGIBLE, so the in-memory PendingAsk must be rebuilt at init."""
    aid = "offload_t1_reasoning"
    seed = _process_view()
    _seed_eligible_ready(seed, aid, clean=authority.PROMOTION_THRESHOLD)
    assert seed.mark_eligible_if_ready(aid, authority.PROMOTION_THRESHOLD) is True

    led = _process_view()                                  # fresh process loads disk
    gate = authority.AuthorityGate(_FakeStore(), led)      # simulates restart
    assert f"{aid}:promotion" in gate.pending, \
        "ELIGIBLE action did not resurface a promotion ask after restart"


def test_gate_construction_resurfaces_nothing_when_no_eligible(ledger_path):
    led = _process_view()
    gate = authority.AuthorityGate(_FakeStore(), led)
    assert gate.pending == {}


# ── H1: shutdown must not flush whole ledger state (clobber risk) ────────────
def test_engine_stop_does_not_flush_ledger(ledger_path):
    """Shutdown previously called ledger.save() to "flush trust counters", but a
    whole-state write from the daemon's possibly-stale in-memory view could
    clobber a mutation a loki-q CLI committed since the last tick's load(). Every
    mutation already persists atomically per-op under the lock, so stop() must
    NOT write the ledger (review H1)."""
    import threading
    from loki.engine import DecisionEngine

    eng = DecisionEngine.__new__(DecisionEngine)   # bypass the heavy __init__
    eng._stop_event = threading.Event()

    class _LedgerSpy:
        saved = False

        def save(self):
            self.saved = True

    eng.ledger = _LedgerSpy()
    eng.stop()

    assert eng._stop_event.is_set(), "stop() must signal the run loop to halt"
    assert eng.ledger.saved is False, \
        "stop() still flushes the ledger — reintroduces the shutdown clobber (H1)"


def test_load_seed_is_an_atomic_rmw_under_lock(ledger_path):
    """The cold-start materialize must re-read under the flock (atomic RMW), not
    publish a lock-the-write-only stale snapshot. Pin that load() routes the seed
    through _materialize_seed (which re-hydrates under the lock) and that a token
    already on disk survives a re-seed of a missing row (review H1)."""
    import json
    seed = _process_view()                          # all rows materialized
    seed.approve_run("offload_t1_reasoning")        # a committed token on disk

    data = json.loads(ledger_path.read_text())
    dropped = next(iter(data["actions"]))           # remove one row → forces a re-seed
    del data["actions"][dropped]
    ledger_path.write_text(json.dumps(data))

    fresh = authority.AuthorityLedger()
    fresh.load()                                    # _hydrate sees a missing row → _materialize_seed

    disk = _process_view()
    assert dropped in disk.records, "re-seed did not restore the missing row"
    assert "offload_t1_reasoning" in disk.approved_runs, \
        "re-seed clobbered a token already committed on disk"


# ── H2: a crashing action must release its in-flight slot ────────────────────
class _BoomAction:
    """Executor whose execute() raises — models a buggy action."""
    def matches(self, params) -> bool:
        return True

    def execute(self, params) -> str:
        raise RuntimeError("boom")


def _make_proposed(action_id="offload_t1_reasoning", dedup="incident-1"):
    from datetime import datetime, timezone
    from loki.schema import ProposedAction
    return ProposedAction(
        action_id=action_id, trigger="test:boom", dedup_key=dedup,
        rationale="unit test", proposed_at=datetime.now(timezone.utc),
    )


def test_crashing_action_releases_in_flight_slot(ledger_path, monkeypatch):
    """If execute() raises, the worker must still release the dedup key and
    enqueue a 'failed' outcome — otherwise is_in_flight stays True forever and
    the action is wedged and can never be re-dispatched (review H2)."""
    import time
    led = _process_view()
    gate = authority.AuthorityGate(_FakeStore(), led)
    monkeypatch.setitem(authority.ACTIONS, "offload_t1_reasoning", _BoomAction())
    proposed = _make_proposed()

    gate._spawn_exec(proposed, emit_kind="silent")

    deadline = time.time() + 5
    while gate.is_in_flight(proposed.dedup_key) and time.time() < deadline:
        time.sleep(0.01)
    assert not gate.is_in_flight(proposed.dedup_key), \
        "a crashing action wedged the in-flight slot"
    assert any(o == "failed" for _, _, o in gate._finished), \
        "crash did not enqueue a failed outcome for finalization"


# ── H4: REAL cross-process concurrency (not a deterministic stand-in) ─────────
def _stress_record_worker(path_str, action_id, n):
    from pathlib import Path
    from loki import authority as _auth
    _auth.AUTHORITY_PATH = Path(path_str)
    led = _auth.AuthorityLedger()
    led.load()
    for _ in range(n):
        led.record(action_id, "ok")


def test_record_no_lost_updates_under_real_process_concurrency(ledger_path):
    """The headline single-writer invariant, proven under ACTUAL parallelism:
    N forked processes each record the same action M times. The flock-held
    read-modify-write must serialize every increment — total_runs must equal
    N*M with zero lost updates (review H4: the prior tests only simulated this
    with two in-memory views called in a fixed order)."""
    import multiprocessing as mp
    aid = "offload_t1_reasoning"
    _process_view()                           # materialize the file + cold-start row
    nproc, nrec = 6, 50
    ctx = mp.get_context("fork")
    procs = [ctx.Process(target=_stress_record_worker, args=(str(ledger_path), aid, nrec))
             for _ in range(nproc)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
    assert all(p.exitcode == 0 for p in procs), "a stress worker crashed"
    disk = _process_view()
    assert disk.records[aid].total_runs == nproc * nrec, (
        f"lost updates under real concurrency: "
        f"{disk.records[aid].total_runs} != {nproc * nrec}")
