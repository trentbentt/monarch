import io
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # import server.py directly
from server import convert_to_wav  # noqa: E402


def _wav_bytes(sr: int = 22050, secs: float = 0.4) -> bytes:
    buf = io.BytesIO()
    data = np.random.uniform(-0.1, 0.1, int(sr * secs)).astype("float32")
    sf.write(buf, data, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def test_convert_to_wav_makes_16k_mono(tmp_path):
    src = tmp_path / "in.wav"
    sf.write(src, np.zeros(22050, dtype="float32"), 22050)  # 1s @ 22050, mono
    dst = tmp_path / "sub" / "out.wav"
    convert_to_wav(src, dst)
    info = sf.info(str(dst))
    assert info.samplerate == 16000
    assert info.channels == 1
    assert info.subtype == "PCM_16"
    assert dst.exists()


from fastapi.testclient import TestClient  # noqa: E402
from server import create_app  # noqa: E402


def test_status_requires_token(tmp_path):
    client = TestClient(create_app(tmp_path, "secret"))
    assert client.get("/status").status_code == 403          # missing token
    assert client.get("/status?token=bad").status_code == 403  # wrong token


def test_status_counts_existing_clips(tmp_path):
    (tmp_path / "positive").mkdir()
    (tmp_path / "positive" / "positive_000.wav").write_bytes(b"x")
    client = TestClient(create_app(tmp_path, "secret"))
    r = client.get("/status?token=secret")
    assert r.status_code == 200
    body = r.json()
    assert body["positive"] == 1
    assert body["fa_audio"] == 0


def test_upload_converts_counts_and_validates(tmp_path):
    client = TestClient(create_app(tmp_path, "secret"))
    files = {"audio": ("clip.webm", _wav_bytes(), "application/octet-stream")}

    # happy path
    r = client.post("/upload?token=secret", files=files, data={"label": "positive"})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1
    saved = list((tmp_path / "positive").glob("*.wav"))
    assert len(saved) == 1
    assert sf.info(str(saved[0])).samplerate == 16000

    # second upload increments and zero-pads distinctly
    r2 = client.post("/upload?token=secret", files=files, data={"label": "positive"})
    assert r2.json()["count"] == 2
    assert len(list((tmp_path / "positive").glob("*.wav"))) == 2

    # nested label path works
    r3 = client.post("/upload?token=secret", files=files,
                     data={"label": "hard_negative/hey_low_key"})
    assert r3.status_code == 200
    assert (tmp_path / "hard_negative" / "hey_low_key").is_dir()

    # bad token / bad label
    assert client.post("/upload?token=bad", files=files,
                       data={"label": "positive"}).status_code == 403
    assert client.post("/upload?token=secret", files=files,
                       data={"label": "nope"}).status_code == 400


def test_index_requires_token_and_static_served(tmp_path):
    client = TestClient(create_app(tmp_path, "secret"))
    assert client.get("/").status_code == 403
    ok = client.get("/?token=secret")
    assert ok.status_code == 200
    assert "text/html" in ok.headers["content-type"]
    js = client.get("/static/app.js")
    assert js.status_code == 200


def test_script_default_is_eval_profile(tmp_path):
    client = TestClient(create_app(tmp_path, "secret"))
    assert client.get("/script").status_code == 403          # token-gated
    r = client.get("/script?token=secret")
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] == "eval"
    labels = [s["label"] for s in body["steps"]]
    assert labels == ["positive", "hard_negative/hey_low_key", "speech_negative", "fa_audio"]
    pos = next(s for s in body["steps"] if s["label"] == "positive")
    assert pos["target"] == 40


def test_script_train_profile_is_positive_heavy(tmp_path):
    client = TestClient(create_app(tmp_path, "secret", profile="train"))
    body = client.get("/script?token=secret").json()
    assert body["profile"] == "train"
    pos = next(s for s in body["steps"] if s["label"] == "positive")
    assert pos["target"] >= 200          # a real training batch, not 40
    # every train-profile label must be an allowed upload label
    from server import ALLOWED_LABELS
    for s in body["steps"]:
        assert s["label"] in ALLOWED_LABELS
