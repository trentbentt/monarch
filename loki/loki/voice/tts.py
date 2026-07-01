"""TTS wrapper using Piper for synthesizing text to speech."""

from __future__ import annotations

import io
import wave
from functools import lru_cache

from piper import PiperVoice

from .config import load_config


@lru_cache(maxsize=1)
def _voice() -> PiperVoice:
    """Load and cache the Piper voice model."""
    return PiperVoice.load(load_config().piper_voice)


def synthesize(text: str) -> bytes:
    """Synthesize `text` to a 16-bit mono WAV byte string via Piper.

    Args:
        text: The text to synthesize.

    Returns:
        A complete RIFF/WAVE byte string in 16-bit PCM mono format.
    """
    text = (text or "").strip() or "."
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        _voice().synthesize_wav(text, wav)
    return buf.getvalue()
