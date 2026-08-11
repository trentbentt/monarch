"""Routing + pending-actions legibility."""
from datetime import datetime, timedelta, timezone

from legibility import derive_routing, enrich_pending


def _state_with_pending():
    soon = (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()
    return {
        "decisions": {
            "pending_asks": [
                {"action_id": "offload_t1_reasoning", "rationale": "VRAM pressure ELEVATED in overnight window",
                 "tier": "ActionTier.TIER_3", "kind": "run", "blocking": False,
                 "proposed_at": "2026-06-21T03:00:00+00:00", "expires_at": soon, "params": {"ngl": 20}},
                {"action_id": "promote_restart", "rationale": "12 clean runs reached",
                 "tier": "ActionTier.TIER_2", "kind": "promotion", "blocking": True,
                 "proposed_at": "2026-06-21T02:00:00+00:00", "expires_at": None, "params": {}},
            ],
            "ledger": [
                {"action_id": "offload_t1_reasoning", "description": "Offload T1 to CPU",
                 "state": "trusted", "current_tier": 3, "target_tier": 3,
                 "clean_run_count": 4, "total_runs": 5, "last_outcome": "ok"},
            ],
        },
        "health": {"components": [
            {"name": "litellm", "status": "healthy", "port": 4000, "response_ms": 12, "last_seen_healthy": "x"},
            {"name": "validation-gate", "status": "healthy", "port": 4100, "response_ms": 30},
            {"name": "lora-dispatcher", "status": "unresponsive", "port": 4200},
        ]},
        "tiers": {
            "t1": {"config": {"active_lora": "news-adapter"}, "performance": {"completions_in_window": 7, "errors_in_window": 1}},
            "t2": {"config": {"active_lora": None}, "performance": {"completions_in_window": 0, "errors_in_window": 0}},
        },
    }


def test_routing_rolls_up_worst_and_lists_loras_traffic():
    r = derive_routing(_state_with_pending())
    assert r["status"] == "crit"            # lora-dispatcher unresponsive
    names = {c["name"] for c in r["components"]}
    assert names == {"litellm", "validation-gate", "lora-dispatcher"}
    assert r["active_loras"] == [{"tier": "t1", "lora": "news-adapter"}]
    assert r["recent_traffic"][0]["tier"] == "t1"


def test_routing_defensive_on_empty():
    r = derive_routing({})
    assert r["status"] == "unknown"
    assert len(r["components"]) == 3


def _state_three_tiers_one_silent():
    """t1 served traffic, t2 reported a genuine zero, t3 never reported at all."""
    return {
        "tiers": {
            "t1": {"performance": {"completions_in_window": 5, "errors_in_window": 2}},
            "t2": {"performance": {"completions_in_window": 0, "errors_in_window": 0}},
            "t3": {"performance": {}},
        },
    }


def test_routing_traffic_meta_separates_unreported_from_idle():
    r = derive_routing(_state_three_tiers_one_silent())
    # t2 is idle and t3 is silent; both are absent from recent_traffic, so the
    # list alone cannot tell them apart — the counts are what distinguishes them.
    assert [t["tier"] for t in r["recent_traffic"]] == ["t1"]
    assert r["traffic_meta"] == {
        "tiers_total": 3,
        "tiers_reporting": 2,      # t1 and t2 reported completions_in_window; t3 did not
        "errors_reporting": 2,     # same for errors_in_window
    }


def test_routing_traffic_meta_counts_a_field_reported_by_nobody():
    """errors_in_window absent everywhere is not every tier reporting zero errors."""
    state = {"tiers": {
        "t1": {"performance": {"completions_in_window": 4}},
        "t2": {"performance": {"completions_in_window": 0}},
    }}
    r = derive_routing(state)
    assert r["traffic_meta"]["tiers_reporting"] == 2
    assert r["traffic_meta"]["errors_reporting"] == 0


def test_routing_traffic_meta_on_empty_state():
    r = derive_routing({})
    assert r["traffic_meta"] == {"tiers_total": 0, "tiers_reporting": 0, "errors_reporting": 0}


def test_pending_enriched_with_ledger_and_veto_countdown():
    out = enrich_pending(_state_with_pending())
    assert len(out) == 2
    # non-blocking veto window sorts first
    first = out[0]
    assert first["action_id"] == "offload_t1_reasoning"
    assert first["blocking"] is False
    assert first["veto_seconds_remaining"] is not None
    assert 60 < first["veto_seconds_remaining"] <= 90
    assert first["description"] == "Offload T1 to CPU"   # ledger join
    assert first["clean_run_count"] == 4
    assert "VRAM pressure" in first["rationale"]
    # blocking ask has no countdown
    blocking = next(p for p in out if p["action_id"] == "promote_restart")
    assert blocking["veto_seconds_remaining"] is None


def test_pending_empty_when_no_asks():
    assert enrich_pending({"decisions": {"pending_asks": []}}) == []
    assert enrich_pending({}) == []
