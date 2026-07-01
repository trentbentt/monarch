"""Disposable tailnet-only recorder for the hey_loki real-mic eval set.

create_app(out_dir, token) and convert_to_wav() are the testable seams; the
module-level `app` reads REALMIC_OUT / REALMIC_TOKEN from the env for uvicorn.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def convert_to_wav(src: Path, dst: Path) -> None:
    """Convert any ffmpeg-decodable audio at `src` to 16 kHz mono s16 wav at `dst`."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(src), "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", str(dst)],
        check=True,
    )


from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

HERE = Path(__file__).resolve().parent
ALLOWED_LABELS = {"positive", "hard_negative/hey_low_key", "speech_negative", "fa_audio"}

# Guided capture scripts. "eval" builds the held-out test set (modest, 4-label).
# "train" collects a large real-mic positive batch to anchor training recall
# (the 2026-06-28 real-mic eval showed recall sags on real voice — the fix is
# real positives in training, kept SEPARATE from the held-out eval set).
PROFILES = {
    "eval": [
        {"label": "positive", "prompt": 'Say:  "hey loki"', "target": 40},
        {"label": "hard_negative/hey_low_key", "prompt": 'Say:  "hey low key"', "target": 20},
        {"label": "speech_negative", "prompt": "Say a normal sentence (NOT the wake word)", "target": 10},
        {"label": "fa_audio", "prompt": "Stay quiet — capture ~10s of your room", "target": 6},
    ],
    # Positives only: the pipeline anchors recall by globbing real wavs into the
    # positive class (inject_real_positives.py). Real negatives have no injection
    # point (negatives = precomputed features + synthetic adversarials) and real-mic
    # discrimination is already perfect, so we don't collect them here.
    "train": [
        {"label": "positive", "prompt": 'Say:  "hey loki"  (vary tone/distance/room)', "target": 250},
    ],
}


def _count(out_dir: Path, label: str) -> int:
    d = out_dir / label
    return len(list(d.glob("*.wav"))) if d.exists() else 0


def create_app(out_dir: Path, token: str, profile: str = "eval") -> FastAPI:
    out_dir = Path(out_dir)
    steps = PROFILES.get(profile, PROFILES["eval"])
    app = FastAPI()
    static_dir = HERE / "static"

    def _check(t: str) -> None:
        if t != token:
            raise HTTPException(status_code=403, detail="bad token")

    @app.get("/status")
    def status(token: str = Query("")):
        _check(token)
        return {label: _count(out_dir, label) for label in ALLOWED_LABELS}

    @app.get("/script")
    def script(token: str = Query("")):
        _check(token)
        return {"profile": profile if profile in PROFILES else "eval", "steps": steps}

    @app.post("/upload")
    async def upload(
        audio: UploadFile = File(...),
        label: str = Form(...),
        token: str = Query(""),
    ):
        _check(token)
        if label not in ALLOWED_LABELS:
            raise HTTPException(status_code=400, detail="bad label")
        data = await audio.read()
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
            tf.write(data)
            tmp = Path(tf.name)
        try:
            idx = _count(out_dir, label)
            slug = label.replace("/", "_")
            dst = out_dir / label / f"{slug}_{idx:03d}.wav"
            try:
                convert_to_wav(tmp, dst)
            except subprocess.CalledProcessError:
                raise HTTPException(status_code=500, detail="ffmpeg conversion failed")
        finally:
            tmp.unlink(missing_ok=True)
        return {"ok": True, "path": str(dst), "count": _count(out_dir, label)}

    @app.get("/")
    def index(token: str = Query("")):
        _check(token)
        return FileResponse(static_dir / "index.html")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app


import os  # noqa: E402

# Module-level app for `uvicorn server:app`. serve.sh sets these env vars.
app = create_app(
    Path(os.environ.get("REALMIC_OUT", HERE.parent / "realmic_eval")),
    os.environ.get("REALMIC_TOKEN", ""),
    os.environ.get("REALMIC_PROFILE", "eval"),
)
