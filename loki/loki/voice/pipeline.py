from __future__ import annotations

from dataclasses import dataclass

from loki.supervisor.client import SupervisorClient

from . import stt, tts

DIDNT_CATCH = "Sorry, I didn't catch that."
OFFLINE_NOTICE = (
    "The supervisor model is offline. Bring up LiteLLM on port 4000 and try again."
)


@dataclass(frozen=True)
class VoiceTurn:
    transcript: str
    reply_text: str
    reply_wav: bytes


def _is_offline(answer: str) -> bool:
    s = answer.lstrip()
    return s.startswith("[supervisor model offline") or s.startswith("[supervisor model returned an unparseable")


def run(wav_bytes: bytes, *, client: SupervisorClient | None = None) -> VoiceTurn:
    """Wake-utterance WAV in → spoken reply out. Read-only: only ask()."""
    t = stt.transcribe(wav_bytes)
    if t.is_empty:
        reply = DIDNT_CATCH
    else:
        answer = (client or SupervisorClient()).ask(t.text)
        reply = OFFLINE_NOTICE if _is_offline(answer) else answer
    return VoiceTurn(transcript=t.text, reply_text=reply, reply_wav=tts.synthesize(reply))
