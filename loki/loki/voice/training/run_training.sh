#!/usr/bin/env bash
# Phase 18 "hey loki" wake-model — environment prep + background training.
# Isolated in the dedicated ~/venv/voice-train venv (the training deps conflict
# with the shared ~/venv/inference and must NOT pollute it — see TRAINING.md).
#
# Usage (from anywhere):
#   ~/projects/loki/loki/voice/training/run_training.sh 2>&1 | tee runs/train.log
# or backgrounded by the controller via Bash run_in_background.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY=~/venv/voice-train/bin/python3
# torch>=2.6 defaults torch.load(weights_only=True), which breaks loading the
# full-pickle checkpoints from piper-sample-generator, the `dp` DeepPhonemizer,
# and speechbrain. All checkpoints here are from trusted sources; this env var
# restores pre-2.6 behavior for every subprocess without per-call-site patches.
export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1
mkdir -p datasets runs

log() { echo "[$(date +%H:%M:%S)] $*"; }

# 0. System libraries the Python deps load at RUNTIME (not pip-installable, need
#    apt + sudo). Fail fast with a clear message rather than deep in training.
#      ffmpeg     -> torchcodec audio decode + clip resampling
#      libespeak-ng -> espeak_phonemizer (piper text frontend)
command -v ffmpeg >/dev/null || { echo "ERROR: ffmpeg not found. Install: sudo apt-get install -y ffmpeg espeak-ng"; exit 1; }
ldconfig -p 2>/dev/null | grep -q libespeak-ng || { echo "ERROR: libespeak-ng missing. Install: sudo apt-get install -y espeak-ng"; exit 1; }

# 1. dscripka piper-sample-generator fork (train.py imports `generate_samples`).
if [ ! -d piper-sample-generator-dscripka ]; then
  log "cloning dscripka/piper-sample-generator"
  git clone --depth 1 https://github.com/dscripka/piper-sample-generator.git piper-sample-generator-dscripka
  # dscripka generate_samples defaults to models/en-us-libritts-high.pt (v1.0.0).
  # The v2.0.0 libritts_r-medium is a different model the generator will NOT load.
  curl -L -o piper-sample-generator-dscripka/models/en-us-libritts-high.pt \
    https://github.com/rhasspy/piper-sample-generator/releases/download/v1.0.0/en-us-libritts-high.pt \
    --create-dirs
fi

# 2. openWakeWord GitHub source (training code) installed editable into voice-train,
#    shadowing the pip 0.4.0 (inference-only) within this venv.
if [ ! -d openWakeWord-src ]; then
  log "cloning dscripka/openWakeWord"
  git clone --depth 1 https://github.com/dscripka/openWakeWord.git openWakeWord-src
fi
log "installing GH openwakeword + training requirements into voice-train"
$PY -m pip install -e ./openWakeWord-src >/dev/null
# training extras the pipeline relies on (mmap dataloader, augmentation, metrics,
# phonemizer, audio codecs). torchcodec needs system ffmpeg; espeak-phonemizer
# needs system libespeak-ng (both checked above).
$PY -m pip install mmap_ninja torchinfo speechbrain audiomentations acoustics \
    datasets deep-phonemizer torchmetrics torchcodec pronouncing mutagen \
    torch-audiomentations espeak-phonemizer webrtcvad >/dev/null || true

# 2b. Compatibility patches (idempotent, safe to re-run). The pinned clones and a
#     few venv packages predate torch>=2.6 / scipy>=1.15 / torchaudio>=2.9 API
#     changes; these files live in gitignored clones / site-packages, so they are
#     re-applied here rather than tracked. Each skips cleanly if already patched.
log "applying compatibility patches"
$PY - <<'PYEOF'
import importlib.util
from pathlib import Path

def pkgfile(mod, *rel):
    # find_spec does NOT execute the module (acoustics fails to import unpatched).
    return Path(importlib.util.find_spec(mod).origin).parent.joinpath(*rel)

def patch(p, old, new, label):
    p = Path(p)
    if not p.exists():
        print(f"  [warn] {label}: {p} missing"); return
    s = p.read_text()
    if new in s:
        print(f"  [skip] {label} (already patched)"); return
    n = s.count(old)
    if n == 0:
        print(f"  [skip] {label} (anchor absent — assume patched/changed)"); return
    assert n == 1, f"{label}: anchor found {n}x (want 1) in {p}"
    p.write_text(s.replace(old, new, 1)); print(f"  [ok]   {label}")

here = Path.cwd()

# A. openWakeWord --convert_to_tflite: action=store_true with a truthy STRING
#    default "False" => tflite always runs (and crashes without onnx_tf).
patch(here / "openWakeWord-src/openwakeword/train.py",
'''        "--convert_to_tflite",
        help="Convert the trained ONNX model to TFLite format",
        action="store_true",
        default="False",
        required=False''',
'''        "--convert_to_tflite",
        help="Convert the trained ONNX model to TFLite format",
        action="store_true",
        default=False,
        required=False''',
      "openWakeWord tflite default")

# B. piper generate_samples: torch.load needs weights_only=False on torch>=2.6
#    (the rhasspy checkpoint is a full pickle from a trusted source).
patch(here / "piper-sample-generator-dscripka/generate_samples.py",
      "    model = torch.load(model_path)\n",
      "    model = torch.load(model_path, weights_only=False)  # trusted release; torch>=2.6\n",
      "piper generate_samples weights_only")

# C. acoustics: scipy>=1.15 renamed sph_harm -> sph_harm_y (directivity unused here).
patch(pkgfile("acoustics", "directivity.py"),
      "from scipy.special import sph_harm  # pylint: disable=no-name-in-module",
'''try:  # pylint: disable=no-name-in-module
    from scipy.special import sph_harm
except ImportError:  # scipy>=1.15 renamed sph_harm -> sph_harm_y
    from scipy.special import sph_harm_y as sph_harm''',
      "acoustics sph_harm shim")

# D. torch_audiomentations: torchaudio>=2.9 removed top-level torchaudio.info;
#    soundfile gives the same metadata without loading the audio.
patch(pkgfile("torch_audiomentations", "utils", "io.py"),
'''        info = torchaudio.info(str(file_path))
        # Deal with backwards-incompatible signature change.
        # See https://github.com/pytorch/audio/issues/903 for more information.
        if type(info) is tuple:
            si, ei = info
            num_samples = si.length
            sample_rate = si.rate
        else:
            num_samples = info.num_frames
            sample_rate = info.sample_rate
        return num_samples, sample_rate''',
'''        import soundfile as _sf
        _si = _sf.info(str(file_path))
        return _si.frames, _si.samplerate''',
      "torch_audiomentations soundfile metadata")
PYEOF

# openWakeWord shared feature front-end (mel + embedding ONNX)
$PY -c "import openwakeword; openwakeword.utils.download_models()" || true

# 3. Datasets.
if [ ! -f datasets/openwakeword_features_ACAV100M_2000_hrs_16bit.npy ]; then
  log "downloading ACAV100M negative features (~GB)"
  curl -L -o datasets/openwakeword_features_ACAV100M_2000_hrs_16bit.npy \
    https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/openwakeword_features_ACAV100M_2000_hrs_16bit.npy
fi
if [ ! -f datasets/validation_set_features.npy ]; then
  log "downloading FP validation features"
  curl -L -o datasets/validation_set_features.npy \
    https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/validation_set_features.npy
fi
if [ ! -d datasets/mit_rirs ] || [ -z "$(ls -A datasets/mit_rirs 2>/dev/null)" ]; then
  log "fetching MIT RIRs via HF datasets"
  $PY - <<'PY' || log "RIR fetch failed — see TRAINING.md to provide RIRs manually"
import os, soundfile as sf
from datasets import load_dataset
os.makedirs("datasets/mit_rirs", exist_ok=True)
ds = load_dataset("davidscripka/MIT_environmental_impulse_responses", split="train", streaming=True)
for i, row in enumerate(ds):
    a = row["audio"]
    sf.write(f"datasets/mit_rirs/rir_{i}.wav", a["array"], a["sampling_rate"])
print("RIRs written")
PY
fi
if [ ! -d datasets/background_clips ] || [ -z "$(ls -A datasets/background_clips 2>/dev/null)" ]; then
  log "background_clips empty — augmentation needs background audio."
  log "See TRAINING.md (AudioSet/FMA). Proceeding may fail at --augment_clips."
  mkdir -p datasets/background_clips
fi

# 4. Train (generate → augment → train) + copy artifact.
log "starting staged training (this is the long part)"
$PY train.py
log "DONE — model at loki/voice/models/hey_loki.onnx"
