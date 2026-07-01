#!/usr/bin/env python3
"""Fold real-microphone 'hey loki' clips into the wake-model positive class.

The dscripka openWakeWord pipeline has no config key for custom positives: the
positive class is built by globbing every *.wav under runs/<model>/positive_train
and positive_test (train.py). So anchoring training on real-mic recall is just a
matter of copying the recorded clips into those two dirs (with a held-out split)
BEFORE --augment_clips, and clearing the stale precomputed feature caches so they
get recomputed with the new clips included.

Source clips come from `serve.sh train` (realmic_train/positive/, gitignored —
operator voice). This is SEPARATE from realmic_eval/, which stays held-out so the
post-retrain recall number remains honest.

Usage:
  inject_real_positives.py [--src realmic_train/positive] [--run runs/hey_loki]
                           [--test-frac 0.15] [--seed 20260628]
Then re-run training (see realmic_recorder/README.md).
"""
from __future__ import annotations

import random
import shutil
import sys
from pathlib import Path


def split_clips(files, test_frac: float, seed: int):
    """Deterministic train/test partition. Always keeps >=1 in each side when
    there are >=2 files (a held-out test of 0 would make positive_test empty)."""
    files = list(files)
    rng = random.Random(seed)
    shuffled = files[:]
    rng.shuffle(shuffled)
    n_test = int(round(len(shuffled) * test_frac))
    if len(shuffled) >= 2:
        n_test = min(max(n_test, 1), len(shuffled) - 1)
    test = shuffled[:n_test]
    train = shuffled[n_test:]
    return train, test


def inject(src_dir, run_dir, test_frac: float = 0.15, seed: int = 20260628) -> dict:
    src = Path(src_dir)
    run = Path(run_dir)
    files = sorted(str(p) for p in src.glob("*.wav"))
    if not files:
        raise SystemExit(f"no .wav in {src} — record a batch first: serve.sh train")

    train, test = split_clips(files, test_frac, seed)
    ptr = run / "positive_train"
    pte = run / "positive_test"
    ptr.mkdir(parents=True, exist_ok=True)
    pte.mkdir(parents=True, exist_ok=True)

    # realmic_ prefix so real clips never clobber the generated synthetic ones
    for f in train:
        shutil.copy2(f, ptr / f"realmic_{Path(f).name}")
    for f in test:
        shutil.copy2(f, pte / f"realmic_{Path(f).name}")

    # stale feature caches would make --augment_clips skip recompute (the §14.1
    # gotcha): drop them so the real clips actually enter the feature set.
    stale = sorted(run.glob("*_features_*.npy"))
    for s in stale:
        s.unlink()

    return {"train": len(train), "test": len(test), "cleared_features": len(stale)}


def main() -> None:
    import argparse
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(here / "realmic_train" / "positive"))
    ap.add_argument("--run", default=str(here / "runs" / "hey_loki"))
    ap.add_argument("--test-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=20260628)
    a = ap.parse_args()
    res = inject(a.src, a.run, a.test_frac, a.seed)
    print(f"injected real positives: train+{res['train']} test+{res['test']} "
          f"(cleared {res['cleared_features']} stale feature files)")
    print("next: re-run training so --augment_clips picks up the new clips "
          "(see realmic_recorder/README.md)")


if __name__ == "__main__":
    main()
