"""
Supervisor LLM client — routes the conversational turn through the existing
monarch LiteLLM router (localhost:4000), so the supervisor inherits the stack's
own model routing, budgets, and quota accounting rather than opening a second,
unaccounted path to a provider. No API key is handled here by design (the router
owns credentials; §schema D4 note: no ANTHROPIC_API_KEY lives on disk).

Stdlib-only (urllib) to avoid expanding requirements.txt. The client degrades
gracefully: if the router is unreachable the supervisor still answers from the
grounded context with a clear "model offline" note instead of raising — the
read/propose machinery does not depend on the LLM being up.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from .context import build_context

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).with_name("system_prompt.md")

LLM_BASE = os.environ.get("LOKI_SUPERVISOR_LLM_BASE", "http://localhost:4000/v1")
# Default to the local interactive Qwen3.6-27B tier (T1, routed as
# qwen3.6-consultancy). It is already resident with headroom, keeps the supervisor
# fully on-box (no cloud key, no egress), and the deterministic daemon it advises
# uses no model at all — so the 27B has ample room for both. The prior default
# (claude-opus-4-8) was never in the router config and 400'd. Override per call
# with LOKI_SUPERVISOR_MODEL (any routable model_name in ~/litellm/config.yaml).
LLM_MODEL = os.environ.get("LOKI_SUPERVISOR_MODEL", "qwen3.6-consultancy")
LLM_TIMEOUT_SEC = float(os.environ.get("LOKI_SUPERVISOR_TIMEOUT", "60"))
# Local router auth. LiteLLM rejects unauthenticated calls (HTTP 401), so the
# client must present the router's master key. This is the CLIENT authenticating
# to the LOCAL router — it grants the supervisor no capability and does not change
# its read-and-propose posture (the key is the same one inference-up/deploy.sh
# already source from ~/.config/inference/api_keys.env). The provider credential
# (ANTHROPIC_API_KEY) still never touches this layer — the router owns that.
LLM_API_KEY = os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("LITELLM_API_KEY")
# Reasoning-capable routed models (kimi-k2.6, deepseek-v4-*) spend tokens in a
# reasoning_content channel before emitting final content; too small a budget
# makes them hit the cap mid-thought and return EMPTY content (finish_reason=
# length). A blank reply from a safety layer is the worst outcome — it hides
# whether the read-only stance was upheld. Give the budget room and surface the
# reasoning if final content is ever missing (see _post_chat).
LLM_MAX_TOKENS = int(os.environ.get("LOKI_SUPERVISOR_MAX_TOKENS", "2500"))
# The supervisor wants grounded answers, not extended chain-of-thought. On a local
# Qwen3.6 tier, thinking mode generates thousands of reasoning tokens and ties up
# T1's single interactive slot for ~100s (blowing the timeout). Suppress it via the
# Qwen/llama.cpp `chat_template_kwargs.enable_thinking` switch. Sent in extra_body so
# LiteLLM forwards it to the backend rather than dropping it as an unknown top-level
# param. Models that don't honor it ignore it. Off by env to LOKI_SUPERVISOR_THINKING=1.
LLM_DISABLE_THINKING = os.environ.get("LOKI_SUPERVISOR_THINKING", "0") not in ("1", "true", "on")


def load_system_prompt() -> str:
    return _PROMPT_PATH.read_text()


class SupervisorClient:
    """Build the grounded turn and call the router. Caller passes the operator's
    question; the client assembles system_prompt + grounded context + question."""

    def __init__(self, base: str = LLM_BASE, model: str = LLM_MODEL) -> None:
        self.base = base.rstrip("/")
        self.model = model
        self.system_prompt = load_system_prompt()

    def build_messages(self, question: str,
                       include_doctrine: Optional[List[str]] = None) -> list:
        context = build_context(question=question, include_doctrine=include_doctrine)
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": context},
            {"role": "user", "content": question},
        ]

    def ask(self, question: str,
            include_doctrine: Optional[List[str]] = None) -> str:
        return self.chat(self.build_messages(question, include_doctrine))

    def chat(self, messages: list) -> str:
        """The single model-call seam. Wraps _post_chat with the offline-degradation
        guard so EVERY caller — plain `ask` and the Phase-B agent loop alike — turns
        a router-down / timeout condition into the '[model offline]' note instead of
        raising a traceback into the operator's turn. The read/propose machinery does
        not depend on the LLM being up (see module docstring); keep that contract in
        ONE place rather than re-implementing (or forgetting) it per call site."""
        try:
            return self._post_chat(messages)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            logger.warning("supervisor LLM unreachable at %s: %s", self.base, exc)
            return ("[supervisor model offline — router unreachable at "
                    f"{self.base}. The grounded context was assembled successfully; "
                    "bring up LiteLLM (port 4000) to get a synthesized answer.]")
        except (ValueError, KeyError, IndexError) as exc:
            # A reachable router that returns a 200 with a non-JSON body or an
            # error-shaped payload (no `choices`) must STILL not raise into the
            # operator's turn — the 'never raise' contract covers a malformed
            # response, not just a dead socket. (JSONDecodeError is a ValueError.)
            logger.warning("supervisor LLM returned an unparseable response from %s: %s",
                           self.base, exc)
            return ("[supervisor model returned an unparseable response from the "
                    f"router at {self.base}. No action was taken; the grounded "
                    "context was assembled successfully. Check the router/model.]")

    def _post_chat(self, messages: list) -> str:
        body = {
            "model": self.model,
            "max_tokens": LLM_MAX_TOKENS,
            "messages": messages,
        }
        if LLM_DISABLE_THINKING:
            # extra_body → LiteLLM forwards verbatim to the backend; chat_template_kwargs
            # is the llama.cpp/Qwen mechanism to turn off the <think> block.
            body["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        payload = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if LLM_API_KEY:
            headers["Authorization"] = f"Bearer {LLM_API_KEY}"
        req = urllib.request.Request(
            f"{self.base}/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read())
        # OpenAI-compatible shape (LiteLLM normalizes providers to this).
        choice = data["choices"][0]
        msg = choice.get("message", {})
        content = (msg.get("content") or "").strip()
        if not content:
            # NEVER return a silent blank. A reasoning model that exhausts the
            # token budget mid-thought leaves content empty but its (correct)
            # read-only reasoning in reasoning_content — surface it, marked, so
            # the operator always sees the supervisor's stance rather than void.
            reasoning = (msg.get("reasoning_content") or "").strip()
            if reasoning:
                content = ("[supervisor produced no final answer before the token "
                           "budget ran out — surfacing its reasoning verbatim. It "
                           "has taken NO action; this is read-only reasoning.]\n\n"
                           + reasoning)
            else:
                content = ("[supervisor returned an empty response from the router "
                           f"(model {self.model}). No action was taken. Retry, or "
                           "set LOKI_SUPERVISOR_MODEL to a non-reasoning model.]")
        if choice.get("finish_reason") == "length":
            content += ("\n\n[note: response hit the max_tokens cap and may be cut "
                        "off — narrow the question or raise LOKI_SUPERVISOR_MAX_TOKENS.]")
        return content
