"""
Phase-B agentic loop tests — the model-driven, multi-step retrieval loop.

What matters and is asserted here:
  1. The loop is READ-ONLY and BOUNDED — only the 5 retrieval functions are
     reachable, an unknown/forged tool never executes, and the loop always
     terminates (forces a final answer at the step budget).
  2. It DEGRADES, never raises — a tool error becomes feedback, not a crash.
  3. It stays ON-MISSION — the operator's verbatim question is re-anchored each
     step (the §8.7 verbatim-anchor principle, applied in-loop; no parallel store).

The model is faked (scripted responses) so the loop is tested deterministically
without a live T1.

Run: ~/venv/inference/bin/python3 -m pytest loki/supervisor/tests/test_agent.py -q
"""

from __future__ import annotations

from loki.supervisor import agent as A
from loki.supervisor import retrieval as R


class FakeClient:
    """Stands in for SupervisorClient: a system_prompt and a scripted _post_chat."""
    def __init__(self, scripted):
        self.system_prompt = "SYS"
        self._scripted = list(scripted)
        self.calls = []

    def _post_chat(self, messages):
        self.calls.append(messages)
        return self._scripted.pop(0)

    def chat(self, messages):
        # Mirrors the real SupervisorClient.chat seam the agent calls through.
        return self._post_chat(messages)


def _agent(client, **kw):
    return A.SupervisorAgent(client=client, base_context_fn=lambda **k: "BASE", **kw)


# ── directive parsing ───────────────────────────────────────────────────────────
def test_parse_directive_extracts_tool_and_args():
    tool, args = A.parse_directive(
        'I should look. RETRIEVE: {"tool": "search_vault", "query": "vram headroom"}')
    assert tool == "search_vault"
    assert args["query"] == "vram headroom"


def test_parse_directive_none_when_plain_answer():
    assert A.parse_directive("The answer is T1 is always-on.") is None


# ── loop behavior ───────────────────────────────────────────────────────────────
def test_agent_retrieves_then_answers(monkeypatch):
    monkeypatch.setattr(R, "search_vault",
                        lambda q, k=5: [R.Snippet("L3", "f", "f §1", 0.1, "vault says X")])
    client = FakeClient([
        'RETRIEVE: {"tool": "search_vault", "query": "why X"}',
        'Based on the retrieved vault note, X because Y.',
    ])
    out = _agent(client).investigate("why X?")
    assert "X because Y" in out
    assert len(client.calls) == 2                       # one tool step, then the answer
    assert any("vault says X" in m["content"] for m in client.calls[1])   # result fed back


def test_agent_answers_immediately_without_tools():
    client = FakeClient(["T1 is always-on per the snapshot."])
    out = _agent(client).investigate("is T1 up?")
    assert "always-on" in out
    assert len(client.calls) == 1                       # no tool round-trips


def test_agent_bounds_iterations_and_forces_answer(monkeypatch):
    monkeypatch.setattr(R, "search_vault",
                        lambda q, k=5: [R.Snippet("L3", "f", "f", 0.1, "hit")])
    # max_steps=3 → 3 tool rounds consume 3 scripted items, then ONE forced-answer
    # call returns the 4th.
    client = FakeClient(['RETRIEVE: {"tool": "search_vault", "query": "x"}'] * 3
                        + ["forced final answer"])
    out = _agent(client, max_steps=3).investigate("loop forever?")
    assert out == "forced final answer"
    assert len(client.calls) == 4                       # 3 tool steps + 1 synthesis
    # the synthesis call is CLEAN: gathered evidence is present, but the retrieval
    # protocol affordance is gone so the model must answer in prose.
    synth = " ".join(m["content"] for m in client.calls[3])
    assert "hit" in synth                               # gathered evidence carried in
    assert "RETRIEVE:" not in synth                     # no protocol affordance offered


def test_agent_rejects_unknown_tool_without_executing():
    client = FakeClient([
        'RETRIEVE: {"tool": "delete_everything", "query": "rm -rf"}',
        "Understood — I will only read.",
    ])
    out = _agent(client).investigate("can you delete?")
    assert "only read" in out
    assert any("not available" in m["content"].lower() for m in client.calls[1])


def test_agent_tool_registry_is_exactly_the_read_fns():
    # The registry is an exact allowlist — the safety guard that no write/propose/act
    # tool can ever sneak in. Phase C adds doctrine_search (name-addressed doctrine);
    # it is still a read-only retrieval function, like the rest.
    assert set(A._TOOLS) == {
        "search_vault", "session_recall", "code_structure",
        "temporal_recall", "doctrine_search", "doctrine_section",
    }
    # every registered tool must resolve to a real retrieval function (no phantom,
    # no non-retrieval surface).
    for tool in A._TOOLS:
        assert callable(getattr(R, tool, None)), f"{tool} is not a retrieval function"


def test_agent_reanchors_verbatim_question_each_step(monkeypatch):
    monkeypatch.setattr(R, "search_vault",
                        lambda q, k=5: [R.Snippet("L3", "f", "f", 0.1, "hit")])
    client = FakeClient(['RETRIEVE: {"tool": "search_vault", "query": "x"}', "answer"])
    _agent(client).investigate("WHAT_IS_THE_VRAM_HEADROOM?")
    assert any("WHAT_IS_THE_VRAM_HEADROOM?" in m["content"] for m in client.calls[1])


def test_agent_tool_error_degrades_not_raises(monkeypatch):
    def boom(q, k=5):
        raise RuntimeError("pg down")
    monkeypatch.setattr(R, "search_vault", boom)
    client = FakeClient(['RETRIEVE: {"tool": "search_vault", "query": "x"}',
                         "answering despite the error"])
    out = _agent(client).investigate("q")
    assert "despite the error" in out
    fed = " ".join(m["content"] for m in client.calls[1]).lower()
    assert "unavailable" in fed or "error" in fed


def test_agent_anti_thrashing_skips_duplicate_retrieval(monkeypatch):
    # The local 27B sometimes repeats the SAME retrieval instead of answering. The
    # duplicate must not re-execute; the model is told it already has it.
    n = {"calls": 0}
    def counting(q, k=5):
        n["calls"] += 1
        return [R.Snippet("L3", "f", "f", 0.1, "hit")]
    monkeypatch.setattr(R, "search_vault", counting)
    client = FakeClient([
        'RETRIEVE: {"tool": "search_vault", "query": "x"}',
        'RETRIEVE: {"tool": "search_vault", "query": "x"}',   # exact duplicate
        "final answer",
    ])
    out = _agent(client).investigate("q")
    assert out == "final answer"
    assert n["calls"] == 1                                    # duplicate NOT re-run
    assert any("already issued" in m["content"].lower() for m in client.calls[2])


def test_agent_forced_final_never_returns_raw_directive(monkeypatch):
    # A model that NEVER answers (always retrieves) must not leak a raw RETRIEVE
    # directive to the operator as if it were the answer.
    monkeypatch.setattr(R, "search_vault",
                        lambda q, k=5: [R.Snippet("L3", "f", "f", 0.1, "hit")])
    client = FakeClient([
        'RETRIEVE: {"tool": "search_vault", "query": "a"}',
        'RETRIEVE: {"tool": "search_vault", "query": "b"}',
        'RETRIEVE: {"tool": "search_vault", "query": "c"}',
        'RETRIEVE: {"tool": "search_vault", "query": "d"}',   # forced-final STILL retrieves
    ])
    out = _agent(client, max_steps=3).investigate("q")
    assert "RETRIEVE:" not in out                             # raw directive never surfaced
    assert out.strip()                                        # and never blank


def test_agent_doctrine_section_tool_uses_file_key_and_section(monkeypatch):
    monkeypatch.setattr(R, "doctrine_section",
                        lambda key, sec: R.Snippet("L6", "memory", f"mem {sec}", 0.0,
                                                    f"section {sec} body")
                        if key == "memory" else None)
    client = FakeClient([
        'RETRIEVE: {"tool": "doctrine_section", "file_key": "memory", "section": "§7.7"}',
        "explained",
    ])
    _agent(client).investigate("explain L7")
    assert any("section §7.7 body" in m["content"] for m in client.calls[1])


# ── regression: fixes from the high-effort code review ──────────────────────────
def test_parse_directive_survives_braces_in_query_value():
    # A brace inside the JSON value used to truncate the non-greedy `\{.*?\}` regex,
    # making json.loads fail → the directive was mis-read as a final answer and the
    # raw control token leaked. raw_decode parses the whole object.
    tool, args = A.parse_directive(
        'RETRIEVE: {"tool": "search_vault", "query": "the {offload} cascade"}')
    assert tool == "search_vault"
    assert args["query"] == "the {offload} cascade"


def test_run_tool_clamps_model_supplied_k(monkeypatch):
    # A model-supplied k must be clamped — it cannot pull an unbounded result set
    # into T1's single-slot context.
    seen = {}
    def fake(q, k=5):
        seen["k"] = k
        return [R.Snippet("L3", "f", "f", 0.1, "hit")]
    monkeypatch.setattr(R, "search_vault", fake)
    A._run_tool("search_vault", {"query": "x", "k": 10000})
    assert seen["k"] == A._MAX_TOOL_K              # huge int clamped
    A._run_tool("search_vault", {"query": "x", "k": "all"})
    assert seen["k"] == R._DEFAULT_K               # non-int → default


def test_run_tool_truncates_oversized_result(monkeypatch):
    big = "z" * 50000
    monkeypatch.setattr(R, "search_vault",
                        lambda q, k=5: [R.Snippet("L3", "f", "f", 0.1, big)])
    out = A._run_tool("search_vault", {"query": "x"})
    assert len(out) <= A._TOOL_RESULT_BUDGET + 100
    assert "truncated" in out


def test_agent_routes_through_guarded_chat_and_degrades_offline(monkeypatch):
    # The agent MUST call client.chat (which swallows URLError into a '[model offline]'
    # note), NEVER _post_chat directly — otherwise `ask --deep` with the router down
    # raises an uncaught traceback at the operator.
    import urllib.error
    from loki.supervisor.client import SupervisorClient
    c = SupervisorClient()
    monkeypatch.setattr(c, "_post_chat",
                        lambda messages: (_ for _ in ()).throw(urllib.error.URLError("down")))
    out = A.SupervisorAgent(client=c, base_context_fn=lambda **k: "BASE").investigate("why T1 down?")
    assert "model offline" in out.lower()          # degraded, not crashed


def test_agent_duplicate_forged_tool_trips_anti_thrash(monkeypatch):
    # A repeated forged tool name must hit the anti-thrash guard, not silently burn
    # a fresh step each time.
    client = FakeClient([
        'RETRIEVE: {"tool": "rm_rf", "query": "a"}',
        'RETRIEVE: {"tool": "rm_rf", "query": "a"}',   # exact duplicate forged tool
        "ok I will only read",
    ])
    out = _agent(client).investigate("q")
    assert "only read" in out
    assert any("do NOT repeat" in m["content"] for m in client.calls[2])


def test_agent_can_call_doctrine_search_tool(monkeypatch):
    # Phase B must be able to pull doctrine BY NAME mid-investigation, the same
    # name→section recall Phase A got. doctrine_search is a "query"-style tool.
    monkeypatch.setattr(R, "doctrine_search",
                        lambda q, k=5: [R.Snippet("L6", "mem.md", "mem.md §7.3 L3 — pgvector",
                                                  0.0, "L3 is pgvector on :5433")])
    assert A._TOOLS.get("doctrine_search") == "query"
    client = FakeClient([
        'RETRIEVE: {"tool": "doctrine_search", "query": "L3 backend"}',
        "L3 is backed by pgvector [L6 mem.md §7.3 L3 — pgvector].",
    ])
    out = _agent(client).investigate("what backs L3?")
    assert "pgvector" in out
    # the tool result was fed back into the second model turn
    assert any("pgvector on :5433" in m["content"] for m in client.calls[1])
