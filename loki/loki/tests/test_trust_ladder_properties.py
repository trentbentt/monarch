"""Property-based invariants for the N=12 authority trust ladder (review C3).

The promote / demote / record state machine is the system's headline safety
mechanism — an LLM-or-rule action can only gain autonomy by climbing an
operator-gated ladder, capped per action. The example-based tests in
test_authority.py pin specific transitions; this asserts the load-bearing
invariants hold under ANY random sequence of operations, the "prove your safety
boundary" rigor the ladder claims.

Skips cleanly if hypothesis isn't installed (it's a dev/CI dep).
"""
import shutil
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402

from loki import authority                                  # noqa: E402
from loki.schema import ActionLifecycleState, ActionTier    # noqa: E402

_AID = "offload_t1_reasoning"
_OPS = ["ok", "failed", "regretted", "promote", "demote", "eligible"]


@settings(max_examples=60, deadline=None)
@given(st.lists(st.sampled_from(_OPS), max_size=40))
def test_trust_ladder_invariants_hold_under_any_sequence(ops):
    d = tempfile.mkdtemp()
    orig = authority.AUTHORITY_PATH
    try:
        # Per-example isolation: a fresh ledger file each run (Hypothesis reuses
        # the test body, so we cannot lean on a function-scoped fixture).
        authority.AUTHORITY_PATH = Path(d) / "authority.json"
        led = authority.AuthorityLedger()
        led.load()
        n_records = 0

        for op in ops:
            if op in ("ok", "failed", "regretted"):
                led.record(_AID, op)
                n_records += 1
            elif op == "promote":
                led.promote(_AID)
            elif op == "demote":
                led.demote(_AID, "test regret")
            elif op == "eligible":
                led.mark_eligible_if_ready(_AID, authority.PROMOTION_THRESHOLD)

            row = led.get(_AID)
            # ── invariants that must hold after EVERY operation ──
            assert row is not None
            assert row.clean_run_count >= 0
            assert row.current_tier in (
                ActionTier.TIER_1, ActionTier.TIER_2, ActionTier.TIER_3)
            # Promotion cap: an action is NEVER more autonomous than its target.
            # ActionTier is an IntEnum where lower = more authority, so the cap is
            # current_tier >= target_tier. promote() only ever moves current down
            # to the cap; it must never overshoot it.
            assert row.current_tier >= row.target_tier
            # Operator regret is a hard reset to the least-autonomous tier.
            if op == "regretted":
                assert row.current_tier == ActionTier.TIER_3
                assert row.clean_run_count == 0

        # The counter never loses or invents a run...
        assert led.get(_AID).total_runs == n_records
        # ...and a fresh process reads back exactly what was committed (durable).
        reread = authority.AuthorityLedger()
        reread.load()
        assert reread.get(_AID).total_runs == n_records
    finally:
        authority.AUTHORITY_PATH = orig
        shutil.rmtree(d, ignore_errors=True)
