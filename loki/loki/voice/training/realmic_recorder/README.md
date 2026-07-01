# hey_loki real-mic eval recorder (disposable)

Collects a held-out **real-microphone** eval set and lets `evaluate.py` score the
shipped `hey_loki.onnx` on it — does it wake for *you*, and does it really confuse
"hey low key"? Tailnet-only, token-gated. Not a permanent service.

## Run

```bash
~/projects/loki/loki/voice/training/realmic_recorder/serve.sh
```
It prints a URL like:
`https://<your-node>.<your-tailnet>.ts.net:8444/?token=XXXX`

Open it on your Mac/iPhone (must be on the tailnet). Allow the mic. Work through
the prompts: "hey loki" ×40, "hey low key" ×20, a normal sentence ×10, ~10s of
room quiet ×6. Record → review → Keep or Re-record. Ctrl-C when done (removes the
:8444 tailscale mapping; leaves n8n :443 and Command Center :8443 untouched).

Clips land 16 kHz mono in `../realmic_eval/<label>/` (gitignored — your voice).

## Score the real set

```bash
cd ~/projects/loki/loki/voice/training
~/venv/voice-train/bin/python3 evaluate.py --data realmic_eval
```
Reports recall, per-confusable rate (incl. hey_low_key), and false-accepts/hour
on YOUR voice/room. Caveat: one voice/room/mic = a point estimate, not field data.

## Raise recall: retrain with real-mic positives

The 2026-06-28 real-mic eval showed strong discrimination (0 false-fires, incl.
"hey low key") but mediocre recall (0.775 @ 0.5; 0.40 @ the old 0.75 threshold).
The durable fix is **real positives in training** to anchor the target. The held-out
`realmic_eval/` set must NOT be used for this (training on your test set inflates
the score) — so collect a *separate* training batch:

1. **Record a training batch** (positives only, ~250, varied tone/distance/room):
   ```bash
   ~/projects/loki/loki/voice/training/realmic_recorder/serve.sh train
   ```
   Same tailnet URL flow; clips land in `../realmic_train/positive/` (gitignored).
   The `train` profile drives the UI via `GET /script`, so it keeps prompting past 40.

2. **Fold them into the positive class** (held-out split + clears stale feature caches):
   ```bash
   cd ~/projects/loki/loki/voice/training
   ~/venv/voice-train/bin/python3 inject_real_positives.py
   ```
   This copies the clips into `runs/hey_loki/positive_train` + `positive_test`
   (prefixed `realmic_`) alongside the synthetic ones — the pipeline trains on every
   `*.wav` it finds there. It also deletes `runs/hey_loki/*_features_*.npy` so
   `--augment_clips` recomputes with the new clips (the stale-feature gotcha).

3. **Retrain** (regenerates features for the augmented positive set, ~hours on the 3090):
   ```bash
   ~/projects/loki/loki/voice/training/run_training.sh 2>&1 | tee runs/retrain.log
   ```

4. **Re-score against the untouched held-out eval** (the honest number):
   ```bash
   ~/venv/voice-train/bin/python3 evaluate.py --data realmic_eval
   ```
   Look for recall climbing at threshold 0.6 while false-accepts/hour stays ~0.
   (Note: `fa_audio_hours` in the eval is tiny — record more room ambient with the
   default `serve.sh` if you want a trustworthy false-accept rate.)

## Throwaway

When finished, the whole `realmic_recorder/` dir can be deleted; only the
`evaluate.py --data` flag and your `realmic_eval/` clips matter afterward.
