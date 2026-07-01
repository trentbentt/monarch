import inspect

from loki.voice import pipeline, stt


class FakeClient:
    def __init__(self, answer):
        self.answer = answer
        self.asked = []

    def ask(self, question, **kw):
        self.asked.append(question)
        return self.answer


def _stub_io(monkeypatch, text):
    monkeypatch.setattr(
        pipeline.stt, "transcribe",
        lambda b: stt.Transcript(text=text, avg_logprob=-0.1, no_speech_prob=0.0),
    )
    monkeypatch.setattr(pipeline.tts, "synthesize", lambda s: b"RIFFwav:" + s.encode())


def test_happy_path(monkeypatch):
    _stub_io(monkeypatch, "what is t1 doing")
    c = FakeClient("T1 is healthy.")
    turn = pipeline.run(b"x", client=c)
    assert c.asked == ["what is t1 doing"]
    assert turn.transcript == "what is t1 doing"
    assert turn.reply_text == "T1 is healthy."
    assert turn.reply_wav == b"RIFFwav:T1 is healthy."


def test_empty_transcript_skips_supervisor(monkeypatch):
    _stub_io(monkeypatch, "   ")
    c = FakeClient("should not be called")
    turn = pipeline.run(b"x", client=c)
    assert c.asked == []
    assert turn.reply_text == pipeline.DIDNT_CATCH


def test_offline_string_becomes_notice(monkeypatch):
    _stub_io(monkeypatch, "hello")
    c = FakeClient("[supervisor model offline — router unreachable at http://localhost:4000]")
    turn = pipeline.run(b"x", client=c)
    assert turn.reply_text == pipeline.OFFLINE_NOTICE


def test_unparseable_string_becomes_notice(monkeypatch):
    _stub_io(monkeypatch, "hello")
    c = FakeClient("[supervisor model returned an unparseable response from the router]")
    turn = pipeline.run(b"x", client=c)
    assert turn.reply_text == pipeline.OFFLINE_NOTICE


def test_pipeline_never_references_propose():
    src = inspect.getsource(pipeline)
    assert "propose" not in src   # authority invariant: read-only ask() only
