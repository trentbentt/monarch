"""
Phase-B agentic retrieval loop — the supervisor's model-driven, multi-step
deep-dive. Where Phase A (context.py) retrieves ONCE, deterministically, before
the model speaks, Phase B lets the model itself decide what to pull, see the
result, and pull again — chasing a thread (vault note → a symbol → its callers →
the answer) the way a human operator would.

Mechanism: a deterministic ReAct text protocol, NOT llama.cpp native tool-calling.
The model emits `RETRIEVE: {json}` to call one read tool or plain prose to answer;
we parse, execute (only our five read functions), feed the result back, and loop.
This is model-agnostic (no --jinja/grammar dependency), fully testable without a
live model, and read-only by construction — the loop can reach nothing but
retrieval.* , so it can never act, write, or propose.

Safety properties (all asserted in tests):
  • READ-ONLY: `_TOOLS` is exactly the five retrieval functions; an unknown or
    forged tool name is rejected and never executed. Proposing stays the explicit,
    operator-driven `loki-supervisor propose` path — never reachable from here.
  • BOUNDED: at most `max_steps` tool rounds, then a forced final answer — the loop
    always terminates (no runaway T1-slot usage).
  • ON-MISSION: the operator's verbatim question is re-anchored into every fed-back
    message (the §8.7 verbatim-anchor principle applied in-loop). No parallel
    checkpoint store is created (memory-arch §14): the loop's context is ephemeral,
    in-process, single-question.
  • DEGRADES: a tool error becomes feedback text, never an exception into the turn.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Callable, List, Optional, Tuple

from . import retrieval
from .client import SupervisorClient
from .context import build_context

logger = logging.getLogger(__name__)

# tool name → argument style ("query" = fn(query, k); "doctrine" = fn(file_key, section)).
# Resolved against the `retrieval` module at call time so a stubbed backend is seen.
_TOOLS = {
    "search_vault": "query",
    "session_recall": "query",
    "code_structure": "query",
    "temporal_recall": "query",
    "doctrine_search": "query",
    "doctrine_section": "doctrine",
}

# Locate the RETRIEVE prefix; the JSON object after it is consumed with a real JSON
# decoder (raw_decode), NOT a brace-counting regex — so a brace inside a query value
# (e.g. "the {offload} cascade") or a nested object no longer truncates the directive
# into invalid JSON and get mis-read as a final answer.
_RETRIEVE_RE = re.compile(r"RETRIEVE:\s*", re.S)
# Max model-driven retrieval rounds before a forced clean synthesis. Kept small by
# default — each round is a full T1 generation on the single interactive slot.
_DEFAULT_MAX_STEPS = int(os.environ.get("LOKI_SUPERVISOR_MAX_STEPS", "3"))
# The agentic path must honor the same budget discipline gather() enforces: a
# model-supplied k and the formatted result size are clamped so one RETRIEVE can't
# pull a huge result set into T1's single-slot context (prefill blowup / length cut).
_MAX_TOOL_K = retrieval._DEFAULT_K
_TOOL_RESULT_BUDGET = int(os.environ.get("LOKI_SUPERVISOR_RETRIEVAL_BUDGET", "8000"))

AGENT_PROTOCOL_PROMPT = """\
## Deep-dive protocol (you may retrieve before answering)

You can pull from the memory architecture, one read at a time, before you answer.
To retrieve, emit EXACTLY one line:

  RETRIEVE: {"tool": "<tool>", ...args}

Available read-only tools:
  - search_vault       {"tool":"search_vault","query":"..."}        semantic over the vault
  - session_recall     {"tool":"session_recall","query":"..."}      Hermes conversation history
  - code_structure     {"tool":"code_structure","query":"Symbol"}   call graph / symbols
  - temporal_recall    {"tool":"temporal_recall","query":"..."}     long-horizon trajectory (L7)
  - doctrine_search    {"tool":"doctrine_search","query":"L3 backend"}  doctrine section BY NAME (no § needed)
  - doctrine_section   {"tool":"doctrine_section","file_key":"memory|system|handoff","section":"§7.7"}

Rules:
  - These tools only READ. You still have no hands: you cannot act, write, or
    promote anything. To propose a registered action, say so in prose — the
    operator runs it; you never execute.
  - Retrieve only when the grounded context lacks what you need. If you already
    have the answer, just ANSWER in prose — do not retrieve for its own sake.
  - For a layer/architecture question ("what is L5?", "what backs L3?") whose §7
    section is not already in your grounded context, pull the authoritative section
    with doctrine_search (by name) before answering — never recite a layer roster
    or a backend from memory.
  - One RETRIEVE per turn. After you see the result, retrieve again or answer.
  - When you answer, ground every claim in a value you were given and cite its
    [locator]. Never invent a number or status.
"""


def _decode_directive(text: str):
    """(start, end, args_dict) of the first RETRIEVE directive in `text`, or None.
    The JSON object is consumed with json.raw_decode so nested / brace-containing
    payloads parse correctly and any trailing prose is ignored."""
    t = text or ""
    m = _RETRIEVE_RE.search(t)
    if not m:
        return None
    brace = t.find("{", m.start())
    if brace == -1:
        return None
    try:
        args, consumed = json.JSONDecoder().raw_decode(t[brace:])
    except (ValueError, TypeError):
        return None
    if not isinstance(args, dict):
        return None
    return (m.start(), brace + consumed, args)


def parse_directive(text: str) -> Optional[Tuple[str, dict]]:
    """Extract a (tool, args) RETRIEVE directive from model output, or None when
    the output is a plain answer / unparseable."""
    decoded = _decode_directive(text)
    if decoded is None:
        return None
    _, _, args = decoded
    tool = args.get("tool")
    if not tool:
        return None
    return (tool, args)


def _strip_directives(text: str) -> str:
    """Remove any RETRIEVE directive(s) from model output so a stray control token
    is never surfaced to the operator as an answer."""
    out = text or ""
    while True:
        decoded = _decode_directive(out)
        if decoded is None:
            return out
        start, end, _ = decoded
        out = out[:start] + out[end:]


def _clamp_k(k) -> int:
    """Coerce a model-supplied k to a sane int in [1, _MAX_TOOL_K]. The model can
    emit anything ("all", 10000, a string); none of it may blow the T1 context."""
    try:
        k = int(k)
    except (TypeError, ValueError):
        return retrieval._DEFAULT_K
    return max(1, min(k, _MAX_TOOL_K))


def _run_tool(tool: str, args: dict) -> str:
    """Execute one read tool. Returns formatted results or a degradation marker —
    never raises. Resolves the function against `retrieval` at call time; the caller
    (investigate) has already validated `tool` is in _TOOLS."""
    fn = getattr(retrieval, tool, None)
    if fn is None:
        return f"[{tool}: not available]"
    try:
        if _TOOLS[tool] == "doctrine":
            snip = fn(args.get("file_key", "memory"), args.get("section", ""))
            snips = [snip] if snip is not None else []
        else:
            snips = fn(args.get("query", ""), _clamp_k(args.get("k"))) or []
    except Exception as exc:                              # degrade, never raise
        return f"[{tool} unavailable: {type(exc).__name__}: {str(exc)[:80]}]"
    if not snips:
        return f"[{tool}: no results]"
    out = retrieval.format_snippets(snips)               # one shared formatter
    if len(out) > _TOOL_RESULT_BUDGET:
        out = out[:_TOOL_RESULT_BUDGET] + "\n…[tool result truncated to fit budget]"
    return out


class SupervisorAgent:
    """Drives the bounded ReAct loop. Reuses SupervisorClient for the model call
    (same local T1 route, same read-only posture) and context.build_context for the
    grounded base block."""

    def __init__(self, client: Optional[SupervisorClient] = None,
                 max_steps: int = _DEFAULT_MAX_STEPS,
                 base_context_fn: Optional[Callable] = None) -> None:
        self.client = client or SupervisorClient()
        self.max_steps = max_steps
        self.base_context_fn = base_context_fn or build_context

    def investigate(self, question: str) -> str:
        # Base grounded context WITH Phase-A query-directed retrieval: if the model
        # answers on step 1 without issuing a RETRIEVE, it must still be at least as
        # grounded as the plain `ask` path — never LESS. The model can retrieve more
        # on top; the small overlap is the price of never shipping an ungrounded turn.
        base = self.base_context_fn(question=question, retrieve=True)
        messages: List[dict] = [
            {"role": "system", "content": self.client.system_prompt},
            {"role": "system", "content": AGENT_PROTOCOL_PROMPT},
            {"role": "system", "content": base},
            {"role": "user", "content": question},
        ]
        seen: set = set()           # anti-thrashing: signatures already retrieved
        gathered: List[str] = []    # tool results, for the no-converge fallback

        for _step in range(self.max_steps):
            out = self.client.chat(messages)             # guarded model call (degrades offline)
            directive = parse_directive(out)
            if directive is None:
                return out                                # plain answer → done
            tool, args = directive
            messages.append({"role": "assistant", "content": out})
            # Signature computed BEFORE the validity check so a repeated forged tool
            # also trips the anti-thrash guard, not just a repeated valid one.
            sig = (tool, json.dumps(args, sort_keys=True, default=str))
            if sig in seen:
                # Repeating the same read wastes a step and a T1 slot — nudge to answer.
                messages.append({"role": "system", "content":
                    f"[you already issued exactly this — do NOT repeat it. "
                    f"ANSWER in prose now from the results above. "
                    f"Operator asked: {question!r}.]"})
                continue
            seen.add(sig)
            if tool not in _TOOLS:
                messages.append({"role": "system", "content":
                    f"[tool {tool!r} is not available — valid tools: {sorted(_TOOLS)}. "
                    f"Re-anchor — the operator asked: {question!r}. "
                    f"RETRIEVE a valid tool or ANSWER in prose.]"})
                continue
            result = _run_tool(tool, args)
            gathered.append(result)
            messages.append({"role": "system", "content":
                f"## tool_result[{tool}] (read fresh this turn — cite by [locator])\n"
                f"{result}\n\n"
                f"[Re-anchor — the operator asked: {question!r}. "
                f"ANSWER now if you can, or RETRIEVE something DIFFERENT.]"})

        # Step budget reached — synthesize. Crucially, this is a CLEAN call without
        # the retrieval protocol: with no RETRIEVE affordance the model cannot keep
        # retrieving and must answer in prose — the Phase-A single-shot behavior the
        # local model handles reliably, now over the evidence the loop gathered.
        return self._synthesize(question, base, gathered)

    def _synthesize(self, question: str, base: str, gathered: List[str]) -> str:
        evidence = "\n\n".join(gathered) if gathered else "(no retrieval succeeded)"
        synth = [
            {"role": "system", "content": self.client.system_prompt},
            {"role": "system", "content":
                base + "\n\n## retrieved_context (gathered this investigation — "
                "read fresh this turn; cite by [locator])\n" + evidence},
            {"role": "user", "content": question},
        ]
        final = self.client.chat(synth)                  # guarded model call (degrades offline)
        if parse_directive(final) is not None:           # defense in depth
            final = _strip_directives(final).strip()
        if not final:
            final = "[No written answer; retrieved evidence:\n" + evidence[:1500] + "]"
        return final
