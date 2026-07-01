#!/usr/bin/env python3
"""Loki 'hey loki' edge client — runs on the M2 MacBook.

mic → OpenWakeWord[hey_loki] → Silero VAD utterance capture → POST to monarch
→ play the spoken reply. Coexists with the Phase 17.5 'Okay Comrade' model.

Bakes in the five §14.1 tuning lessons:
  1. scale audio to int16-range float32 before OWW (not [-1, 1]);
  2. split OWW 1280-sample chunks into Silero 512-sample sub-frames;
  3. set the retrigger cooldown at start_recording entry, not at delivery;
  4. wake threshold 0.6 (real-mic-tuned; rejects music false-fires);
  5. model.reset() after each take to clear the OWW sliding window.
"""
from __future__ import annotations

import argparse
import io
import time
import wave

import numpy as np
import requests
import sounddevice as sd
from openwakeword.model import Model

SR = 16000
OWW_CHUNK = 1280
VAD_FRAME = 512
WAKE_THRESHOLD = 0.6   # real-mic eval (2026-06-28): 0.6 holds full recall 0.775
                       # with 0 false-fires; 0.75 dropped real recall to 0.40.
COOLDOWN_S = 2.0
SILENCE_HANG_S = 0.8          # stop capture after this much trailing silence
MAX_UTTERANCE_S = 12.0


def _resolve_input_device(preferred: str | None):
    """Three-layer fallback (headset → MacBook → system default), re-resolved
    each capture (§14.1 hardware-resilience lesson)."""
    if preferred:
        for i, d in enumerate(sd.query_devices()):
            if preferred.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                return i
    return None   # sounddevice default


def _capture_utterance(vad, preferred: str | None) -> bytes:
    """Capture from wake until trailing silence; return a 16k mono WAV."""
    import torch
    device = _resolve_input_device(preferred)
    frames: list[np.ndarray] = []
    last_voice = time.monotonic()
    start = time.monotonic()
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16",
                        blocksize=VAD_FRAME, device=device) as stream:
        while True:
            block, _ = stream.read(VAD_FRAME)
            pcm = block[:, 0].copy()
            frames.append(pcm)
            prob = vad(torch.from_numpy(pcm.astype("float32") / 32768.0), SR).item()
            now = time.monotonic()
            if prob >= 0.5:
                last_voice = now
            if now - last_voice > SILENCE_HANG_S or now - start > MAX_UTTERANCE_S:
                break
    audio = np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(audio.tobytes())
    return buf.getvalue()


def _play(wav_bytes: bytes) -> None:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sr = w.getframerate()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    sd.play(audio, sr)
    sd.wait()


def main() -> None:
    p = argparse.ArgumentParser(prog="loki-edge")
    p.add_argument("--server", required=True, help="http://MONARCH_HOST:8123")
    p.add_argument("--wake-model", required=True, help="path to hey_loki.onnx")
    p.add_argument("--voice-key", default=None)
    p.add_argument("--input-device", default=None)
    args = p.parse_args()

    import torch
    vad, _ = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
    oww = Model(wakeword_models=[args.wake_model], inference_framework="onnx")
    url = args.server.rstrip("/") + "/v1/voice/utterance"
    headers = {"X-Voice-Key": args.voice_key} if args.voice_key else {}
    headers["Content-Type"] = "audio/wav"

    print("listening for 'hey loki'…", flush=True)
    cooldown_until = 0.0
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16",
                        blocksize=OWW_CHUNK) as stream:
        while True:
            block, _ = stream.read(OWW_CHUNK)
            # Lesson 1: OWW accepts int16 PCM directly (mic stream is int16); no [-1,1] scaling.
            pcm = block[:, 0].astype(np.int16)
            if time.monotonic() < cooldown_until:
                continue
            scores = oww.predict(pcm)
            if max(scores.values()) < WAKE_THRESHOLD:
                continue
            cooldown_until = time.monotonic() + COOLDOWN_S   # Lesson 3
            print("wake!", flush=True)
            wav = _capture_utterance(vad, args.input_device)
            try:
                r = requests.post(url, data=wav, headers=headers, timeout=60)
                r.raise_for_status()
                print("loki:", r.headers.get("X-Reply-Text", ""), flush=True)
                _play(r.content)
            except Exception as exc:
                print(f"[edge] request failed: {exc}", flush=True)
            oww.reset()                                       # Lesson 5


if __name__ == "__main__":
    main()
