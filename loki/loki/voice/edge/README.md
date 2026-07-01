# Loki "hey loki" edge client (M2 MacBook)

Runs the wake word at the edge; only the post-wake utterance + reply audio
cross the network. Coexists with the LIVE Phase 17.5 "Okay Comrade" dictation —
it adds a second, independent OpenWakeWord model and does not modify that system.

## Install (on the MacBook)
    python3 -m venv ~/venv/loki-edge && source ~/venv/loki-edge/bin/activate
    pip install openwakeword sounddevice requests torch numpy
    # copy hey_loki.onnx from monarch: loki/voice/models/hey_loki.onnx

## Run
    python client.py \
      --server http://MONARCH_HOST:8123 \
      --wake-model ~/loki/hey_loki.onnx \
      --voice-key "$LOKI_VOICE_KEY" \
      --input-device "MacBook"

## monarch side
On monarch, start the service bound to the LAN with a shared key:
    LOKI_VOICE_HOST=0.0.0.0 LOKI_VOICE_KEY=… loki-voice start
(run it in the `whisper` tmux window under the `control` session, §14.3).

## UAT checklist
- [ ] "hey loki — what's T1 doing?" → spoken answer within a few seconds
- [ ] music / TV playing → no false wake (threshold 0.75)
- [ ] "Okay Comrade" still dictates (no regression)
- [ ] mic unplug/replug mid-session → recovers (device re-resolved per capture)
