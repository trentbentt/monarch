import importlib

from loki.voice import config as cfgmod


def test_defaults_loopback(monkeypatch):
    for k in ("LOKI_VOICE_HOST", "LOKI_VOICE_PORT", "LOKI_VOICE_KEY",
              "LOKI_VOICE_WAKE_THRESHOLD"):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(cfgmod)
    c = cfgmod.load_config()
    assert c.host == "127.0.0.1"
    assert c.port == 8123
    assert c.voice_key is None
    assert c.wake_threshold == 0.6
    assert c.stt_model == "large-v3-turbo"


def test_env_override(monkeypatch):
    monkeypatch.setenv("LOKI_VOICE_PORT", "9999")
    monkeypatch.setenv("LOKI_VOICE_KEY", "s3cret")
    importlib.reload(cfgmod)
    c = cfgmod.load_config()
    assert c.port == 9999
    assert c.voice_key == "s3cret"
