#!/usr/bin/env python3
"""Build a statistically meaningful, held-out evaluation set for the hey_loki
wake model.

Why this exists: the original data/ eval set was 5 positives + 16 negatives, all
at 22050 Hz (the model wants 16 kHz). That is too small to measure recall and
the wrong sample rate corrupts every score. This script generates a large
held-out set with piper (a fixed eval seed, distinct from training draws) and
resamples everything to canonical 16 kHz mono s16.

Independence caveat: positives are piper-TTS, same engine/distribution as
training (different random draws, not disjoint speakers). This reliably catches
a broken model and measures confusable-phrase discrimination, but does NOT
prove real-microphone performance — only real recordings can do that.

Output layout (under ./eval_data):
  positive/                 ~500 "hey loki"
  hard_negative/<phrase>/   ~100 each confusable phrase
  speech_negative/          ~200 general English sentences
FP-per-hour audio is taken at eval time from datasets/background_clips +
speech_negative (see evaluate.py).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
PIPER = HERE / "piper-sample-generator-dscripka"
sys.path.insert(0, str(PIPER))
from generate_samples import generate_samples  # noqa: E402

OUT = HERE / "eval_data"
EVAL_SEED = 20260627  # fixed, distinct from training; makes the set reproducible

N_POS = 500
N_HARD = 100
N_SPEECH = 200

HARD_NEGATIVES = {
    "hey": "hey",
    "loki": "loki",
    "okay_comrade": "okay comrade",
    "hey_low_key": "hey low key",
    "hey_loaded": "hey loaded",
    "you_may_begin": "you may begin",
}

# Varied general sentences so normal conversation is represented (not the wake
# word, no confusable fragments).
SPEECH = [
    "the weather today is cold and clear",
    "please remember to buy milk and bread",
    "i think the meeting is scheduled for tuesday",
    "can you turn down the music a little",
    "the train was delayed by twenty minutes",
    "she wants to visit the museum this weekend",
    "we should probably leave before it gets dark",
    "my favorite color has always been deep blue",
    "the recipe calls for two cups of flour",
    "he forgot his umbrella at the office again",
    "the children are playing in the backyard",
    "i need to charge my phone before we go",
    "the coffee shop on the corner is closed",
    "let me know when you arrive at the station",
    "the garden looks beautiful in the spring",
    "they watched a documentary about the ocean",
    "could you pass me the salt and pepper",
    "the library closes early on sundays",
    "we drove along the coast for three hours",
    "her presentation went really well yesterday",
]


def _resample_dir(raw: Path, dest: Path) -> int:
    """Resample every wav in raw/ to 16 kHz mono s16 into dest/. Returns count."""
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for w in sorted(raw.glob("*.wav")):
        out = dest / w.name
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(w), "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", str(out)],
            check=True,
        )
        n += 1
    return n


def _gen(text, n: int, dest: Path, tmp: Path) -> int:
    raw = tmp / dest.name
    raw.mkdir(parents=True, exist_ok=True)
    generate_samples(text=text, output_dir=str(raw), max_samples=n, batch_size=50)
    return _resample_dir(raw, dest)


def main() -> None:
    torch.manual_seed(EVAL_SEED)
    if OUT.exists():
        shutil.rmtree(OUT)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print(f"[eval-build] positives: {N_POS}")
        c = _gen("hey loki", N_POS, OUT / "positive", tmp)
        print(f"  -> {c} positive clips @ 16k")

        for slug, phrase in HARD_NEGATIVES.items():
            print(f"[eval-build] hard negative '{phrase}': {N_HARD}")
            c = _gen(phrase, N_HARD, OUT / "hard_negative" / slug, tmp)
            print(f"  -> {c} clips @ 16k")

        print(f"[eval-build] speech negatives: {N_SPEECH}")
        c = _gen(SPEECH, N_SPEECH, OUT / "speech_negative", tmp)
        print(f"  -> {c} clips @ 16k")

    print("[eval-build] DONE")


if __name__ == "__main__":
    main()
