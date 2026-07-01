# Training the "hey loki" wake model

The wake model is trained with openWakeWord's **GitHub** training pipeline. The
pip package (`openwakeword==0.4.0`) ships inference only — there is no
`openwakeword.train`. So the real pipeline lives in the cloned GH repo and runs
in a **dedicated venv** (`~/venv/voice-train`), isolated from the shared
`~/venv/inference` whose pip-check must stay clean.

## Why a separate venv
`piper-sample-generator` pins `piper-tts==1.3.0`; the runtime service uses
`piper-tts==1.4.2`. Installing the training stack into `~/venv/inference` breaks
its `pip check` (the monarch infra invariant). `~/venv/voice-train` was created
with `--system-site-packages` (reuses system torch/onnxruntime) and holds the
conflicting/heavy training deps. `pip check` is clean in both venvs.

## One command
```bash
~/projects/loki/loki/voice/training/run_training.sh 2>&1 | tee \
  ~/projects/loki/loki/voice/training/runs/train.log
```
`run_training.sh` is idempotent: it clones the repos, installs the GH
`openwakeword` (editable, shadowing the pip one inside voice-train), downloads
the datasets, then runs `train.py` (generate → augment → train) and copies the
result to `loki/voice/models/hey_loki.onnx`.

## Datasets (downloaded into ./datasets/)
| File / dir | Source | Note |
|---|---|---|
| `openwakeword_features_ACAV100M_2000_hrs_16bit.npy` | HF `davidscripka/openwakeword_features` | precomputed **negative** training features (~GB) |
| `validation_set_features.npy` | same HF repo | false-positive validation set |
| `mit_rirs/` | HF `davidscripka/MIT_environmental_impulse_responses` | room impulse responses for augmentation |
| `background_clips/` | **you provide** | background audio to mix in (AudioSet `agkphysics/AudioSet` or FMA-small `https://github.com/mdeff/fma`). Required by `--augment_clips`. |

`background_clips/` is the one piece `run_training.sh` cannot fetch cheaply
(AudioSet/FMA are large). Drop a few hundred 16 kHz wavs of speech/noise/music
there before the augment stage, or point `background_paths` in
`training_config.yaml` at an existing corpus.

## Config
`training_config.yaml` (schema mirrors `openWakeWord-src/examples/custom_model.yml`).
Key knobs: `n_samples` (positive synthetic count; 20k floor, 100k+ for a strong
model), `steps`, `max_negative_weight`/`target_false_positives_per_hour` (govern
the FP/recall tradeoff). `custom_negative_phrases` already excludes "okay
comrade"/"you may begin" so "hey loki" stays distinct from Phase 17.5 (§14.2).

## Verify the model
After training, score it (uses the shared venv's openwakeword inference + the
committed `evaluate.py`):
```bash
~/venv/inference/bin/python3 loki/voice/training/evaluate.py
```
Gate: `recall ≥ 0.8`, `false_activation_rate ≤ 0.02`. If it fails, raise
`n_samples`/`augmentation_rounds`/`steps` and retrain.

## Known compatibility risks
- The GH training code predates torch 2.12; if a stage errors on a torch/
  torchaudio API, pin the versions the repo's `requirements` specify inside
  voice-train (does not touch the shared venv).
- `train.py` imports `generate_samples` from **dscripka's** piper-sample-generator
  fork (cloned as `piper-sample-generator-dscripka/`), not rhasspy's 3.2.0.
