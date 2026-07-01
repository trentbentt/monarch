import io
import wave
from pathlib import Path

import pytest

from loki.voice import tts


def _tts_model_present() -> bool:
    """True only if the Piper voice model is installed. Lets the audio tests skip
    cleanly on machines / CI without the voice stack instead of failing — the
    suite stays honestly green everywhere (review C2)."""
    try:
        from loki.voice.config import load_config
        return Path(load_config().piper_voice).exists()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _tts_model_present(), reason="piper TTS voice model not installed")


def test_synthesize_returns_valid_wav():
    data = tts.synthesize("testing one two three")
    assert data[:4] == b"RIFF"
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2          # 16-bit PCM
        assert w.getnframes() > 0
