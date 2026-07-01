#!/usr/bin/env python3
"""Generate positive ("hey loki") and hard-negative clips for wake-model training.

Drives rhasspy/piper-sample-generator (invoked as ``python -m piper_sample_generator``).
Positives vary speaker/prosody via the generator's built-in SLERP sampling;
negatives are confusable phrases that must NOT trigger the wake word.

Real CLI (discovered from ``python3 -m piper_sample_generator --help``):
    python3 -m piper_sample_generator <text> \
        --model <path.pt> \
        --max-samples <n> \
        --output-dir <dir> \
        [--batch-size <n>] \
        [--max-speakers <n>]

Usage:
    # Full production run (default counts):
    python3 loki/voice/training/gen_samples.py

    # Cheap smoke run (override via env vars):
    POSITIVE_COUNT=5 NEGATIVE_COUNT=2 python3 loki/voice/training/gen_samples.py

Environment variables:
    POSITIVE_COUNT    Number of "hey loki" clips  (default: 2000)
    NEGATIVE_COUNT    Clips per negative phrase    (default: 200)
    BATCH_SIZE        Generator CUDA batch size    (default: 10)
    MAX_SPEAKERS      Speaker pool limit           (default: 200)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Checkpoint lives inside the cloned piper-sample-generator subdir.
MODEL = HERE / "piper-sample-generator" / "models" / "en_US-libritts_r-medium.pt"

# ---------------------------------------------------------------------------
# Configurable counts — override with env vars for cheap smoke runs.
# ---------------------------------------------------------------------------
POSITIVE_COUNT: int = int(os.environ.get("POSITIVE_COUNT", 2000))
NEGATIVE_COUNT: int = int(os.environ.get("NEGATIVE_COUNT", 200))
BATCH_SIZE: int = int(os.environ.get("BATCH_SIZE", 10))
MAX_SPEAKERS: int = int(os.environ.get("MAX_SPEAKERS", 200))

# ---------------------------------------------------------------------------
# Negative (hard-negative) phrases — confusable, must NOT wake.
# ---------------------------------------------------------------------------
NEGATIVE_PHRASES: list[str] = [
    "hey",
    "loki",
    "okay comrade",
    "hey low key",
    "hey loaded",
    "hey google",
    "hello there",
    "you may begin",
]


def _gen(phrase: str, out_dir: Path, n: int) -> None:
    """Run piper_sample_generator for *phrase*, saving *n* WAVs to *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "piper_sample_generator",
        phrase,
        "--model", str(MODEL),
        "--max-samples", str(n),
        "--output-dir", str(out_dir),
        "--batch-size", str(BATCH_SIZE),
        "--max-speakers", str(MAX_SPEAKERS),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    if not MODEL.exists():
        raise FileNotFoundError(
            f"Checkpoint not found: {MODEL}\n"
            "Run: wget -O <path> "
            "https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/en_US-libritts_r-medium.pt"
        )

    data = HERE / "data"

    print(f"[gen_samples] positive={POSITIVE_COUNT}, negative_per_phrase={NEGATIVE_COUNT}")
    _gen("hey loki", data / "positive", POSITIVE_COUNT)

    for i, phrase in enumerate(NEGATIVE_PHRASES):
        _gen(phrase, data / "negative" / f"neg_{i}", NEGATIVE_COUNT)

    pos = len(list((data / "positive").glob("*.wav")))
    neg = len(list((data / "negative").rglob("*.wav")))
    print(f"positive={pos} negative={neg}")


if __name__ == "__main__":
    main()
