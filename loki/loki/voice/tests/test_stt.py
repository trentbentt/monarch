import importlib
from pathlib import Path

import pytest

from loki.voice import config as cfgmod
from loki.voice import stt, tts


def _tts_model_present() -> bool:
    """Skip cleanly without the Piper voice model (review C2)."""
    try:
        from loki.voice.config import load_config
        return Path(load_config().piper_voice).exists()
    except Exception:
        return False


def _use_tiny(monkeypatch):
    monkeypatch.setenv("LOKI_VOICE_STT_MODEL", "tiny")
    monkeypatch.setenv("LOKI_VOICE_STT_DEVICE", "cpu")
    monkeypatch.setenv("LOKI_VOICE_STT_COMPUTE", "int8")
    importlib.reload(cfgmod)
    stt._model.cache_clear()


@pytest.mark.skipif(not _tts_model_present(), reason="piper TTS voice model not installed")
def test_transcribes_known_phrase(monkeypatch):
    _use_tiny(monkeypatch)
    wav = tts.synthesize("testing one two three")
    t = stt.transcribe(wav)
    assert not t.is_empty
    assert "test" in t.text.lower()


def test_silence_is_empty(monkeypatch):
    _use_tiny(monkeypatch)
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)   # 1s silence
    t = stt.transcribe(buf.getvalue())
    assert t.is_empty
