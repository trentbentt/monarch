import http.client
import threading

from loki.voice import service
from loki.voice.config import VoiceConfig
from loki.voice.pipeline import VoiceTurn


def _cfg(key=None):
    return VoiceConfig(
        host="127.0.0.1", port=8137, voice_key=key, stt_model="tiny",
        stt_device="cpu", stt_compute_type="int8", piper_voice="x",
        wake_model="x", wake_threshold=0.75,
    )


def _serve(cfg):
    turn = VoiceTurn(transcript="hi there", reply_text="hello back", reply_wav=b"RIFFreply")
    srv = service.make_server(cfg, runner=lambda wav: turn)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_round_trip_and_headers():
    cfg = _cfg()
    srv = _serve(cfg)
    try:
        c = http.client.HTTPConnection(cfg.host, cfg.port)
        c.request("POST", "/v1/voice/utterance", body=b"audio")
        r = c.getresponse()
        body = r.read()
        assert r.status == 200
        assert r.getheader("Content-Type") == "audio/wav"
        assert r.getheader("X-Transcript") == "hi there"
        assert r.getheader("X-Reply-Text") == "hello back"
        assert body == b"RIFFreply"
    finally:
        srv.shutdown()


def test_auth_required_when_key_set():
    cfg = _cfg(key="s3cret")
    srv = _serve(cfg)
    try:
        c = http.client.HTTPConnection(cfg.host, cfg.port)
        c.request("POST", "/v1/voice/utterance", body=b"audio")  # no key
        assert c.getresponse().status == 401
        c = http.client.HTTPConnection(cfg.host, cfg.port)
        c.request("POST", "/v1/voice/utterance", body=b"audio",
                  headers={"X-Voice-Key": "s3cret"})
        assert c.getresponse().status == 200
    finally:
        srv.shutdown()


def test_healthz():
    cfg = _cfg()
    srv = _serve(cfg)
    try:
        c = http.client.HTTPConnection(cfg.host, cfg.port)
        c.request("GET", "/healthz")
        r = c.getresponse()
        assert r.status == 200
        assert b"ok" in r.read()
    finally:
        srv.shutdown()
