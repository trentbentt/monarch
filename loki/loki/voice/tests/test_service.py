"""The voice service's HTTP surface — round trip, auth, health, and isolation.

M239. Every fixture here used to bind a FIXED port, 127.0.0.1:8137, and
`_serve` only ever called `srv.shutdown()` — which stops `serve_forever` and
does NOT close the listening socket. Two consequences, both measured 2026-08-19:

  * Two suites touching this file cannot run at once. This tree and its
    published copy under monarch-public are byte-identical, and
    `monarch-exit-check` runs both as legs; with any peer session running the
    other one, whichever process loses the bind fails all three tests with
    `OSError: [Errno 98] Address already in use` in ~1.3s while the winner
    passes in ~2.8s. Reproduced 3 of 3 — the loser is decided by scheduling,
    not by anything either tree did.
  * It reads as a flake. It turned the gate's `public/loki` leg red mid-sweep
    while the sweep budget was being re-derived, and cost a real investigation
    before the cause turned out to be four characters. A red that is nobody's
    fault and nobody's to fix is the same thing as a red nobody looks at (M99),
    and it reached the M223 public-parity prover's control, where an
    already-red published suite would have made every withheld row pass for
    the wrong reason.

So the port is asked for, never chosen: `port=0` lets the OS assign a free one
and `srv.server_address[1]` reports which. The tests connect to THAT, not to the
config, because the config no longer knows. `_stop` closes the socket it opened.

The failure was loud here (bind refused) rather than silent (connecting to the
other process's server, reading its identical fixture data, and passing), and
that was ordering, not design — nothing asserted it was talking to the server it
started. Two servers now run side by side in one test, which is the direct
statement of that property.
"""
import http.client
import threading

from loki.voice import service
from loki.voice.config import VoiceConfig
from loki.voice.pipeline import VoiceTurn


def _cfg(key=None, port=0):
    """port=0 = "any free port". A literal here is the defect (M239)."""
    return VoiceConfig(
        host="127.0.0.1", port=port, voice_key=key, stt_model="tiny",
        stt_device="cpu", stt_compute_type="int8", piper_voice="x",
        wake_model="x", wake_threshold=0.75,
    )


def _serve(cfg):
    turn = VoiceTurn(transcript="hi there", reply_text="hello back", reply_wav=b"RIFFreply")
    srv = service.make_server(cfg, runner=lambda wav: turn)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _port(srv):
    """The port the socket ACTUALLY got — cfg.port is 0 and stays 0."""
    return srv.server_address[1]


def _stop(srv):
    """`shutdown()` stops serving; `server_close()` releases the socket.

    Only the first was ever called, so the port stayed bound until the process
    exited — which is why even a second bind inside one process failed.
    """
    srv.shutdown()
    srv.server_close()


def _conn(srv):
    return http.client.HTTPConnection("127.0.0.1", _port(srv))


def test_round_trip_and_headers():
    srv = _serve(_cfg())
    try:
        c = _conn(srv)
        c.request("POST", "/v1/voice/utterance", body=b"audio")
        r = c.getresponse()
        body = r.read()
        assert r.status == 200
        assert r.getheader("Content-Type") == "audio/wav"
        assert r.getheader("X-Transcript") == "hi there"
        assert r.getheader("X-Reply-Text") == "hello back"
        assert body == b"RIFFreply"
    finally:
        _stop(srv)


def test_auth_required_when_key_set():
    srv = _serve(_cfg(key="s3cret"))
    try:
        c = _conn(srv)
        c.request("POST", "/v1/voice/utterance", body=b"audio")  # no key
        assert c.getresponse().status == 401
        c = _conn(srv)
        c.request("POST", "/v1/voice/utterance", body=b"audio",
                  headers={"X-Voice-Key": "s3cret"})
        assert c.getresponse().status == 200
    finally:
        _stop(srv)


def test_healthz():
    srv = _serve(_cfg())
    try:
        c = _conn(srv)
        c.request("GET", "/healthz")
        r = c.getresponse()
        assert r.status == 200
        assert b"ok" in r.read()
    finally:
        _stop(srv)


# ── M239 · the two properties the fixed port cost, stated directly ──────────

def test_two_voice_services_can_run_at_once():
    """The cross-suite collision, reduced to one process.

    Written red: against the fixed port this raised
    `OSError: [Errno 98] Address already in use` on the second bind, which is
    exactly what one sweep did to another session's.

    Both are then USED, not merely constructed — two servers that bind
    successfully and answer on the wrong socket would satisfy a bind-only
    assertion, and identical fixture data is what would hide it.
    """
    a = _serve(_cfg())
    b = _serve(_cfg())
    try:
        assert _port(a) != _port(b), "both servers took the same port"
        for srv in (a, b):
            c = _conn(srv)
            c.request("GET", "/healthz")
            assert c.getresponse().status == 200
    finally:
        _stop(a)
        _stop(b)


def test_the_port_is_released_when_the_service_stops():
    """`shutdown()` alone is not a close, and the difference is invisible until
    something rebinds. Asking for the SAME port back is the only way to state
    it: with port 0 a second server would simply be handed a different one and
    the assertion would pass without the socket ever having been closed.
    """
    first = _serve(_cfg())
    port = _port(first)
    _stop(first)

    second = _serve(_cfg(port=port))
    try:
        assert _port(second) == port
    finally:
        _stop(second)
