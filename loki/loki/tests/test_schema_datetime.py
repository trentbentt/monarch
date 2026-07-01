"""SystemModel datetime defaults must be timezone-AWARE (review C7).

Naive datetime.utcnow() defaults raise `can't subtract offset-naive and
offset-aware datetimes` the moment any consumer subtracts them from a tz-aware
now() (e.g. a Command Center freshness check).
"""
from loki import schema


def test_model_datetime_defaults_are_tz_aware():
    assert schema.SystemModel().last_updated.tzinfo is not None
    assert schema.Schedule().generated_at.tzinfo is not None
    assert schema.Event(event_id="x", type="t").timestamp.tzinfo is not None
