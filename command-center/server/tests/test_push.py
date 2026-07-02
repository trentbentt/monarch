"""Web Push: VAPID keys, notification-decision logic, subscriptions, bridge."""
import base64
from datetime import datetime

import config
from push import bridge, subscriptions, vapid


# --- VAPID -------------------------------------------------------------------

def test_vapid_keygen_and_app_server_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUSH_KEYS_PATH", tmp_path / "vapid.json")
    monkeypatch.setattr(vapid, "_priv", None)
    key = vapid.application_server_key()
    # base64url decodes to a 65-byte uncompressed EC point (0x04 prefix)
    pad = "=" * (-len(key) % 4)
    raw = base64.urlsafe_b64decode(key + pad)
    assert len(raw) == 65 and raw[0] == 0x04
    assert "BEGIN PRIVATE KEY" in vapid.private_pem()
    # persisted + stable across reload
    monkeypatch.setattr(vapid, "_priv", None)
    assert vapid.application_server_key() == key


def test_private_key_b64_is_consumable_by_pyvapid(tmp_path, monkeypatch):
    # Regression: sender must hand pywebpush the raw base64url scalar, not a PKCS8
    # PEM string. py_vapid.Vapid.from_string is exactly what pywebpush calls; a PEM
    # string raises "Could not deserialize key data" and every push fails locally.
    monkeypatch.setattr(config, "PUSH_KEYS_PATH", tmp_path / "vapid.json")
    monkeypatch.setattr(vapid, "_priv", None)
    from py_vapid import Vapid
    raw = vapid.private_key_b64()
    pad = "=" * (-len(raw) % 4)
    assert len(base64.urlsafe_b64decode(raw + pad)) == 32
    Vapid.from_string(raw)  # must not raise


# --- decision logic ----------------------------------------------------------

_PREFS = {"overnight_window_start": "23:00", "overnight_window_end": "07:00"}
_IN_WINDOW = datetime(2026, 6, 21, 3, 0)     # 03:00 local
_OUT_WINDOW = datetime(2026, 6, 21, 12, 0)   # 12:00 local


def test_interrupt_class_bypasses_quiet_window():
    ev = {"type": "gpu_thermal_critical", "severity": "critical"}
    assert bridge.should_notify(ev, _PREFS, _IN_WINDOW) is True


def test_non_interrupt_critical_suppressed_in_window():
    ev = {"type": "tier_unhealthy", "severity": "critical"}
    assert bridge.should_notify(ev, _PREFS, _IN_WINDOW) is False


def test_non_interrupt_critical_fires_outside_window():
    ev = {"type": "tier_unhealthy", "severity": "critical"}
    assert bridge.should_notify(ev, _PREFS, _OUT_WINDOW) is True


def test_info_event_never_pushes():
    ev = {"type": "tier_unhealthy", "severity": "info"}
    assert bridge.should_notify(ev, _PREFS, _OUT_WINDOW) is False


def test_overnight_window_wraps_midnight():
    assert bridge.in_overnight_window(_PREFS, datetime(2026, 6, 21, 2, 0)) is True
    assert bridge.in_overnight_window(_PREFS, datetime(2026, 6, 21, 23, 30)) is True
    assert bridge.in_overnight_window(_PREFS, datetime(2026, 6, 21, 12, 0)) is False


# --- subscriptions -----------------------------------------------------------

def test_subscriptions_upsert_and_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUSH_SUBS_PATH", tmp_path / "subs.json")
    assert subscriptions.count() == 0
    subscriptions.add({"endpoint": "https://push/abc", "keys": {}})
    subscriptions.add({"endpoint": "https://push/abc", "keys": {"p256dh": "x"}})  # upsert
    assert subscriptions.count() == 1
    subscriptions.add({"endpoint": "https://push/def"})
    assert subscriptions.count() == 2
    subscriptions.remove("https://push/abc")
    assert subscriptions.count() == 1


# --- bridge ------------------------------------------------------------------

def test_bridge_primes_then_dispatches_new_events(monkeypatch):
    sent = []
    monkeypatch.setattr(bridge.sender, "send_all", lambda payload: sent.append(payload))
    b = bridge.PushBridge(watcher=None)
    # priming snapshot: existing events recorded, NOT replayed
    s1 = {"events": {"log": [{"event_id": "e1", "type": "info", "severity": "info"}]},
          "operator": {"preferences": _PREFS}}
    b._handle(s1)
    assert sent == []
    # new interrupt event -> dispatched
    s2 = {"events": {"log": [
        {"event_id": "e1", "type": "info", "severity": "info"},
        {"event_id": "e2", "type": "spend_burst", "severity": "critical", "detail": ">$5 in 5min"},
    ]}, "operator": {"preferences": _PREFS}}
    b._handle(s2)
    assert len(sent) == 1
    assert sent[0]["tag"] == "spend_burst"


def test_send_one_survives_bad_subscription(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUSH_KEYS_PATH", tmp_path / "v.json")
    monkeypatch.setattr(vapid, "_priv", None)
    from push import sender
    # invalid p256dh/auth -> pywebpush raises a non-WebPushException; must not propagate
    ok, status = sender.send_one(
        {"endpoint": "https://push.example/x", "keys": {"p256dh": "x", "auth": "y"}},
        {"title": "t", "body": "b"},
    )
    assert ok is False


def test_send_all_survives_bad_subscription(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUSH_KEYS_PATH", tmp_path / "v.json")
    monkeypatch.setattr(config, "PUSH_SUBS_PATH", tmp_path / "subs.json")
    monkeypatch.setattr(vapid, "_priv", None)
    from push import sender
    subscriptions.add({"endpoint": "https://push.example/x", "keys": {"p256dh": "x", "auth": "y"}})
    result = sender.send_all({"title": "t", "body": "b"})   # must not raise
    assert result["sent"] == 0 and result["failed"] == 1


def test_bridge_skips_already_seen(monkeypatch):
    sent = []
    monkeypatch.setattr(bridge.sender, "send_all", lambda payload: sent.append(payload))
    b = bridge.PushBridge(watcher=None)
    s = {"events": {"log": [{"event_id": "e1", "type": "security_alert", "severity": "critical"}]},
         "operator": {"preferences": _PREFS}}
    b._handle(s)        # prime
    b._handle(s)        # same events -> nothing new
    assert sent == []
