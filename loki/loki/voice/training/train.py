#!/usr/bin/env python3
"""Phase 18 "hey loki" wake-model training orchestrator.

Thin driver over openWakeWord's GitHub training entrypoint
(./openWakeWord-src/openwakeword/train.py), which is NOT shipped in the pip
package (0.4.0 has inference only). Assumes the environment and datasets are
already prepared by run_training.sh:
  - ./openWakeWord-src/                 (cloned openWakeWord GitHub repo)
  - ./piper-sample-generator-dscripka/  (dscripka fork train.py imports)
  - ./datasets/                         (feature .npy, RIRs, background clips)
  - the voice-train venv has the GH openwakeword installed (editable)

Runs the staged flow (generate → augment → train), then copies the trained
model to loki/voice/models/hey_loki.onnx.

Run under the dedicated training venv:
  ~/venv/voice-train/bin/python3 loki/voice/training/train.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
GH_TRAIN = HERE / "openWakeWord-src" / "openwakeword" / "train.py"
CONFIG = HERE / "training_config.yaml"
PRODUCED = HERE / "runs" / "hey_loki.onnx"  # export_model writes output_dir/<name>.onnx
DEST = REPO_ROOT / "loki" / "voice" / "models" / "hey_loki.onnx"


def _stage(*flags: str) -> None:
    cmd = [sys.executable, str(GH_TRAIN), "--training_config", str(CONFIG), *flags]
    print(f"\n=== {' '.join(flags)} ===", flush=True)
    subprocess.run(cmd, cwd=str(HERE), check=True)


def main() -> None:
    if not GH_TRAIN.exists():
        sys.exit(f"missing {GH_TRAIN} — run run_training.sh first to clone the repo")
    # Staged so a failure is attributable; each stage is resumable on its own.
    _stage("--generate_clips")
    _stage("--augment_clips")
    _stage("--train_model")

    if not PRODUCED.exists():
        sys.exit(f"training finished but {PRODUCED} not found")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PRODUCED, DEST)
    # ONNX export uses external data: copy the weights sidecar too, or onnxruntime
    # fails at load with "External data path does not exist".
    sidecar = PRODUCED.with_suffix(".onnx.data")
    if sidecar.exists():
        shutil.copy2(sidecar, DEST.with_suffix(".onnx.data"))
        print(f"wrote {DEST.with_suffix('.onnx.data')}")
    print(f"\nwrote {DEST}")


if __name__ == "__main__":
    main()
