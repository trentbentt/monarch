#!/usr/bin/env python3
"""Score the hey_loki wake model against a large, held-out evaluation set.

Replaces the original toy harness (5 positives / 16 negatives, all 22050 Hz fed
to a 16 kHz model — every score corrupted). This version:
  - reads any wav and resamples to canonical 16 kHz (the rate bug can't recur),
  - measures recall over ~500 held-out positives,
  - measures confusable-phrase discrimination per hard-negative bucket,
  - measures false-accepts-per-hour over hours of ambience + speech,
  - sweeps the threshold so we pick an operating point instead of guessing.

Build the set first with: build_eval_set.py

Honest ceiling: positives are piper-TTS (same engine as training, held-out
draws). This catches broken models and measures discrimination; it does NOT
prove real-microphone performance. Only real recordings can.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

FRAME = 1280                 # openWakeWord step size (80 ms @ 16 kHz)
SR = 16000
PAD_S = 1.0                  # leading/trailing silence so the OWW streaming buffer
                             # warms up (short isolated clips otherwise never fill
                             # the 16-frame window — depresses recall ~40 pts).
REFRACTORY_FRAMES = 13       # ~1 s: don't count one activation event many times
THRESHOLDS = [0.5, 0.6, 0.7, 0.75, 0.8, 0.9]
OP_THRESHOLD = 0.5           # operating point the gate is judged at
GATE_RECALL = 0.80
GATE_FA_PER_HOUR = 1.0


def read_16k(path: Path) -> np.ndarray:
    data, sr = sf.read(str(path), dtype="int16", always_2d=False)
    if data.ndim > 1:
        data = data[:, 0]
    if sr != SR:
        from scipy.signal import resample
        f = data.astype(np.float32)
        n = int(round(len(f) * SR / sr))
        data = np.clip(resample(f, n), -32768, 32767).astype(np.int16)
    return data


def frame_scores(model, audio: np.ndarray) -> list[float]:
    """Per-frame peak wake score. Resets sliding window first (stale OWW state
    leaks between clips — the §14.1 lesson)."""
    model.reset()
    out = []
    for i in range(0, len(audio) - FRAME + 1, FRAME):
        scores = model.predict(audio[i:i + FRAME])
        out.append(max(scores.values()))
    return out


def peak_scores_for_dir(model, wav_dir: Path) -> list[float]:
    clips = sorted(Path(wav_dir).rglob("*.wav"))
    sil = np.zeros(int(PAD_S * SR), dtype=np.int16)
    peaks = []
    for c in clips:
        audio = np.concatenate([sil, read_16k(c), sil])  # buffer warmup
        fs = frame_scores(model, audio)
        peaks.append(max(fs) if fs else 0.0)
    return peaks


def fa_events(frame_lists: list[list[float]], threshold: float) -> int:
    events = 0
    for scores in frame_lists:
        last = -10 ** 9
        for idx, sc in enumerate(scores):
            if sc >= threshold and (idx - last) >= REFRACTORY_FRAMES:
                events += 1
                last = idx
    return events


def rate_at(peaks: list[float], threshold: float) -> float:
    if not peaks:
        return 0.0
    return sum(1 for p in peaks if p >= threshold) / len(peaks)


def resolve_eval_dirs(here: Path, data_dir):
    eval_data = Path(data_dir) if data_dir else here / "eval_data"
    fa = eval_data / "fa_audio"
    fa_source = fa if fa.exists() else here / "datasets" / "background_clips"
    return {
        "positive": eval_data / "positive",
        "hard_negative": eval_data / "hard_negative",
        "speech_negative": eval_data / "speech_negative",
        "fa_source": fa_source,
        "eval_data": eval_data,
    }


def main(data_dir=None) -> None:
    from openwakeword.model import Model
    root = Path(__file__).resolve().parents[3]
    here = Path(__file__).resolve().parent
    dirs = resolve_eval_dirs(here, data_dir)
    if not dirs["positive"].exists():
        sys.exit(f"{dirs['positive']} missing — build the eval set first")

    model = Model(
        wakeword_models=[str(root / "loki/voice/models/hey_loki.onnx")],
        inference_framework="onnx",
    )

    # --- clip-level peaks (computed once, swept over thresholds) ---
    print("scoring positives...", file=sys.stderr)
    pos_peaks = peak_scores_for_dir(model, dirs["positive"])
    hard_peaks = {}
    if dirs["hard_negative"].exists():
        for d in sorted(dirs["hard_negative"].iterdir()):
            if d.is_dir():
                print(f"scoring hard_negative/{d.name}...", file=sys.stderr)
                hard_peaks[d.name] = peak_scores_for_dir(model, d)
    print("scoring speech negatives...", file=sys.stderr)
    speech_peaks = peak_scores_for_dir(model, dirs["speech_negative"]) \
        if dirs["speech_negative"].exists() else []

    # --- false-accepts-per-hour: stream over hours of non-wake audio ---
    print("scoring FA/hour audio (ambience + speech)...", file=sys.stderr)
    fa_files = sorted(dirs["fa_source"].rglob("*.wav"))
    fa_files += sorted(dirs["speech_negative"].rglob("*.wav")) \
        if dirs["speech_negative"].exists() else []
    fa_frames = []
    total_frames = 0
    for f in fa_files:
        fs = frame_scores(model, read_16k(f))
        fa_frames.append(fs)
        total_frames += len(fs)
    fa_hours = total_frames * FRAME / SR / 3600.0

    # --- sweep ---
    sweep = []
    for t in THRESHOLDS:
        row = {
            "threshold": t,
            "recall": round(rate_at(pos_peaks, t), 4),
            "hard_negative_rate": round(
                rate_at([p for ps in hard_peaks.values() for p in ps], t), 4),
            "speech_negative_rate": round(rate_at(speech_peaks, t), 4),
            "false_accepts_per_hour": round(fa_events(fa_frames, t) / fa_hours, 3)
                if fa_hours else 0.0,
        }
        sweep.append(row)

    op = next(r for r in sweep if r["threshold"] == OP_THRESHOLD)
    report = {
        "model": str(root / "loki/voice/models/hey_loki.onnx"),
        "set_sizes": {
            "positive": len(pos_peaks),
            "hard_negative": {k: len(v) for k, v in hard_peaks.items()},
            "speech_negative": len(speech_peaks),
            "fa_audio_hours": round(fa_hours, 2),
        },
        "per_hard_negative_rate_at_op": {
            k: round(rate_at(v, OP_THRESHOLD), 4) for k, v in hard_peaks.items()
        },
        "operating_point": op,
        "threshold_sweep": sweep,
        "caveat": "piper-TTS held-out set; measures discrimination, not real-mic performance",
    }
    print(json.dumps(report, indent=2))

    ok = (op["recall"] >= GATE_RECALL
          and op["false_accepts_per_hour"] <= GATE_FA_PER_HOUR)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None,
                    help="eval set dir (default: ./eval_data). Use realmic_eval for real-mic data.")
    main(ap.parse_args().data)
