from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
MODELS_DIR = PKG_DIR / "models"


@dataclass(frozen=True)
class VoiceConfig:
    host: str
    port: int
    voice_key: str | None
    stt_model: str
    stt_device: str
    stt_compute_type: str
    piper_voice: str
    wake_model: str
    wake_threshold: float


def load_config() -> VoiceConfig:
    return VoiceConfig(
        host=os.environ.get("LOKI_VOICE_HOST", "127.0.0.1"),
        port=int(os.environ.get("LOKI_VOICE_PORT", "8123")),
        voice_key=os.environ.get("LOKI_VOICE_KEY") or None,
        stt_model=os.environ.get("LOKI_VOICE_STT_MODEL", "large-v3-turbo"),
        stt_device=os.environ.get("LOKI_VOICE_STT_DEVICE", "cuda"),
        stt_compute_type=os.environ.get("LOKI_VOICE_STT_COMPUTE", "float16"),
        piper_voice=os.environ.get(
            "LOKI_VOICE_PIPER_VOICE",
            str(MODELS_DIR / "en_US-lessac-medium.onnx"),
        ),
        wake_model=os.environ.get(
            "LOKI_VOICE_WAKE_MODEL", str(MODELS_DIR / "hey_loki.onnx")
        ),
        wake_threshold=float(os.environ.get("LOKI_VOICE_WAKE_THRESHOLD", "0.6")),
    )
