import subprocess
from pathlib import Path

import pytest

# Repo root derived from this file's location (loki/voice/tests/test_cli.py),
# never a hardcoded operator path — keeps the public tree username-free.
REPO_ROOT = str(Path(__file__).resolve().parents[3])
BIN = "bin/loki-voice"


def _tts_model_present() -> bool:
    """Skip cleanly without the Piper voice model (review C2)."""
    try:
        from loki.voice.config import load_config
        return Path(load_config().piper_voice).exists()
    except Exception:
        return False


@pytest.mark.skipif(not _tts_model_present(),
                    reason="piper TTS voice model not installed (loki-voice say needs it)")
def test_say_writes_wav(tmp_path):
    out = tmp_path / "r.wav"
    r = subprocess.run(
        ["./" + BIN, "say", "hello there", "--no-play", "--out", str(out)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert out.exists() and out.read_bytes()[:4] == b"RIFF"


def test_help():
    r = subprocess.run(["./" + BIN, "--help"],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0
    assert "start" in r.stdout and "say" in r.stdout
