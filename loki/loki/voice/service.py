from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import VoiceConfig, load_config
from . import pipeline


def _hdr(s: str) -> str:
    """ASCII-safe, single-line header value (avoid header injection / encode errors)."""
    return s.replace("\n", " ").replace("\r", " ")[:512].encode("ascii", "replace").decode()


def make_handler(cfg: VoiceConfig, runner):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, ctype: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            if cfg.voice_key is None:
                return True
            return self.headers.get("X-Voice-Key") == cfg.voice_key

        def do_GET(self):
            if self.path == "/healthz":
                self._send(200, "application/json",
                           json.dumps({"ok": True, "stt_model": cfg.stt_model}).encode())
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self):
            if self.path != "/v1/voice/utterance":
                self._send(404, "text/plain", b"not found")
                return
            if not self._authed():
                self._send(401, "text/plain", b"unauthorized")
                return
            n = int(self.headers.get("Content-Length", "0"))
            wav = self.rfile.read(n)
            try:
                turn = runner(wav)
            except Exception as exc:  # never 500-crash the loop silently
                self._send(500, "text/plain", str(exc).encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("X-Transcript", _hdr(turn.transcript))
            self.send_header("X-Reply-Text", _hdr(turn.reply_text))
            self.send_header("Content-Length", str(len(turn.reply_wav)))
            self.end_headers()
            self.wfile.write(turn.reply_wav)

        def log_message(self, *_a):  # silence default stderr logging
            pass

    return Handler


def make_server(cfg: VoiceConfig | None = None, runner=None) -> ThreadingHTTPServer:
    cfg = cfg or load_config()
    runner = runner or pipeline.run
    return ThreadingHTTPServer((cfg.host, cfg.port), make_handler(cfg, runner))
