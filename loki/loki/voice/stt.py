from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache

from faster_whisper import WhisperModel

from .config import load_config


@dataclass(frozen=True)
class Transcript:
    text: str
    avg_logprob: float
    no_speech_prob: float

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@lru_cache(maxsize=1)
def _model() -> WhisperModel:
    cfg = load_config()
    return WhisperModel(
        cfg.stt_model, device=cfg.stt_device, compute_type=cfg.stt_compute_type
    )


def transcribe(wav_bytes: bytes) -> Transcript:
    """Transcribe a WAV byte string. faster-whisper decodes + resamples to 16k
    via its bundled PyAV, so any sample rate / channel count is accepted."""
    segments, _info = _model().transcribe(
        io.BytesIO(wav_bytes), language="en", vad_filter=True
    )
    segs = list(segments)
    text = " ".join(s.text.strip() for s in segs).strip()
    if segs:
        avg_logprob = sum(s.avg_logprob for s in segs) / len(segs)
        no_speech = sum(s.no_speech_prob for s in segs) / len(segs)
    else:
        avg_logprob, no_speech = -10.0, 1.0
    return Transcript(text=text, avg_logprob=avg_logprob, no_speech_prob=no_speech)
