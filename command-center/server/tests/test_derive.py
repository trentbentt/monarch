"""Contract tests for the derive layer against the real-shaped fixture."""
from derive import derive_overview
from models import StatusLevel, worst


EXPECTED_DOMAINS = {
    "tiers", "vitals", "routing", "memory", "workflows",
    "schedule", "authority", "events", "spend", "docs",
}


def test_overview_covers_all_ten_domains(state):
    ov = derive_overview(state)
    keys = {d.key for d in ov.domains}
    assert keys == EXPECTED_DOMAINS, f"missing/extra domains: {keys ^ EXPECTED_DOMAINS}"
    assert len(ov.domains) == 10


def test_overview_overall_is_worst_of_domains(state):
    ov = derive_overview(state)
    expected = worst([d.status for d in ov.domains])
    # stale spine can only raise overall, never lower it
    assert ov.overall.rank >= expected.rank


def test_attention_sorted_worst_first(state):
    ov = derive_overview(state)
    ranks = [a.status.rank for a in ov.attention]
    assert ranks == sorted(ranks, reverse=True)


def test_derive_is_defensive_on_empty_state():
    ov = derive_overview({})
    assert len(ov.domains) == 10
    assert ov.stale is False  # no last_updated -> age unknown -> not stale
    # every domain degrades, never raises
    assert all(isinstance(d.status, StatusLevel) for d in ov.domains)


def test_derive_flags_stale_state():
    ov = derive_overview({"last_updated": "2000-01-01T00:00:00+00:00"})
    assert ov.stale is True
    assert ov.overall.rank >= StatusLevel.WARN.rank
    assert any(a.domain == "daemon" for a in ov.attention)


def test_tiers_summary_counts_live(state):
    ov = derive_overview(state)
    tiers = next(d for d in ov.domains if d.key == "tiers")
    assert "live" in tiers.counts and "total" in tiers.counts
    assert tiers.counts["live"] <= tiers.counts["total"]
