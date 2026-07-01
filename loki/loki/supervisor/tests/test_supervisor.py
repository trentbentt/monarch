"""
Supervisor layer tests — focused on the SAFETY boundary, not the LLM.

What matters here is that the layer cannot exceed its authority or destabilize the
daemon: it proposes only registered actions, it reads state without writing it, it
degrades gracefully when the model is offline, and the engine drains its queue
through the same gate a rule uses — behind a default-off flag.

Run under the monarch venv:
  ~/venv/inference/bin/python3 -m pytest loki/supervisor/tests -q
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from loki.actions import ACTIONS
from loki.supervisor.proposals import SupervisorProposalQueue, SUPERVISOR_SOURCE


@pytest.fixture
def queue(tmp_path) -> SupervisorProposalQueue:
    return SupervisorProposalQueue(path=tmp_path / "supervisor_proposals.json")


# ── hallucination defense (layer 1: submit) ─────────────────────────────────────
def test_submit_rejects_unknown_action(queue):
    with pytest.raises(ValueError):
        queue.submit("rm_rf_everything", "definitely not a real action")


def test_submit_accepts_registered_action(queue):
    aid = next(iter(ACTIONS))
    p = queue.submit(aid, "a grounded reason")
    assert p.action_id == aid
    assert p.dedup_key == f"{SUPERVISOR_SOURCE}:{aid}"
    assert p.trigger.startswith(SUPERVISOR_SOURCE)
    # Provenance the gate enforces on — non-rule origin can never auto-fire or
    # earn trust (see the authority-gate tests below).
    assert p.origin == SUPERVISOR_SOURCE


# ── hallucination defense (layer 2: drain re-validates) ─────────────────────────
def test_drain_drops_unknown_action_even_if_handwritten(queue):
    # Simulate a corrupt/hand-edited queue file with a phantom action.
    queue.path.parent.mkdir(parents=True, exist_ok=True)
    queue.path.write_text(json.dumps([{
        "action_id": "phantom_action",
        "trigger": "supervisor:operator_review",
        "params": {},
        "dedup_key": "supervisor:phantom_action",
        "rationale": "injected",
        "proposed_at": "2026-06-21T00:00:00+00:00",
    }]))
    drained = queue.drain()
    assert drained == []            # phantom dropped
    assert queue.pending() == []    # queue cleared


def test_drain_returns_valid_and_clears(queue):
    aid = next(iter(ACTIONS))
    queue.submit(aid, "reason one")
    drained = queue.drain()
    assert len(drained) == 1
    assert drained[0].action_id == aid
    assert queue.pending() == []    # drained => cleared (no replay next tick)


def test_drain_forces_supervisor_origin_on_handwritten_entry(queue):
    # A hand-edited entry that omits/forges `origin` must NOT escape the Tier-3
    # floor: drain stamps supervisor-origin on everything it yields, because the
    # queue's provenance is intrinsic, not data-dependent.
    aid = next(iter(ACTIONS))
    queue.path.parent.mkdir(parents=True, exist_ok=True)
    queue.path.write_text(json.dumps([{
        "action_id": aid,
        "trigger": "supervisor:operator_review",
        "params": {},
        "dedup_key": f"{SUPERVISOR_SOURCE}:{aid}",
        "rationale": "forged to look like a rule",
        "proposed_at": "2026-06-21T00:00:00+00:00",
        "origin": "rule",                       # forged provenance
    }]))
    drained = queue.drain()
    assert len(drained) == 1
    assert drained[0].origin == SUPERVISOR_SOURCE   # forced back to supervisor


def test_drain_empty_is_safe(queue):
    assert queue.drain() == []


# ── read-only context grounding ─────────────────────────────────────────────────
def test_context_builds_without_state(monkeypatch, tmp_path):
    # Point state/ledger at empty paths; context must still build and must say so
    # rather than inventing values.
    monkeypatch.setenv("LOKI_STATE_PATH", str(tmp_path / "nostate.json"))
    monkeypatch.setenv("LOKI_AUTHORITY_PATH", str(tmp_path / "noauth.json"))
    # Reload modules that captured the env path at import time.
    import importlib
    import loki.state as state_mod
    import loki.supervisor.context as ctx_mod
    importlib.reload(state_mod)
    importlib.reload(ctx_mod)

    block = ctx_mod.build_context()
    assert "no state.json on disk yet" in block
    assert "registered_actions" in block
    # The proposable-actions list must reflect the real registry.
    for aid in ACTIONS:
        assert aid in block


def test_registered_actions_matches_registry():
    from loki.supervisor.context import registered_actions
    ids = {a["action_id"] for a in registered_actions()}
    assert ids == set(ACTIONS)


# ── query-directed retrieval injection (Phase A) ────────────────────────────────
def test_build_context_injects_retrieved_block_with_provenance(monkeypatch):
    import loki.supervisor.context as ctx_mod
    import loki.supervisor.retrieval as R
    fake = R.RetrievalResult(
        snippets=[R.Snippet(
            layer="L3", source="final_memory_architecture.md",
            locator="final_memory_architecture.md §7.7", score=0.1,
            text="EverMemOS consolidates MemCells into MemScenes.")],
        notes=["L5 unavailable: TimeoutError"],
        layers=["L3"],
    )
    monkeypatch.setattr(R, "gather", lambda *a, **k: fake)

    block = ctx_mod.build_context("how does L7 consolidation work?")

    assert "retrieved_context" in block
    assert "EverMemOS consolidates MemCells" in block
    assert "final_memory_architecture.md §7.7" in block      # locator cited for grounding
    assert "L5 unavailable" in block                          # degradation surfaced, not hidden
    assert "GROUNDED CONTEXT" in block                        # disk-is-truth banner preserved


def test_build_context_without_question_skips_retrieval(monkeypatch):
    # Back-compat: the no-question call (e.g. `loki-supervisor context`) must not
    # invoke retrieval and must still build the base block.
    import loki.supervisor.context as ctx_mod
    import loki.supervisor.retrieval as R
    calls = {"n": 0}
    def spy(*a, **k):
        calls["n"] += 1
        return R.RetrievalResult([], [], [])
    monkeypatch.setattr(R, "gather", spy)

    block = ctx_mod.build_context()
    assert calls["n"] == 0
    assert "registered_actions" in block


def test_build_messages_forwards_question_to_retrieval(monkeypatch):
    # The seam fix: client must thread the operator's question into context so
    # retrieval is query-directed (previously build_context never saw the question).
    import loki.supervisor.retrieval as R
    seen = {}
    monkeypatch.setattr(R, "gather",
                        lambda question, *a, **k: seen.update(q=question) or
                        R.RetrievalResult([], [], []))
    from loki.supervisor.client import SupervisorClient
    SupervisorClient().build_messages("why did T1 offload last night?")
    assert seen.get("q") == "why did T1 offload last night?"


# ── graceful degradation when the model is offline ──────────────────────────────
def test_client_degrades_when_router_unreachable(monkeypatch):
    from loki.supervisor.client import SupervisorClient
    # Force an unroutable base so the call fails fast and predictably.
    monkeypatch.setenv("LOKI_SUPERVISOR_LLM_BASE", "http://127.0.0.1:1/v1")
    import importlib
    import loki.supervisor.client as client_mod
    importlib.reload(client_mod)
    client = client_mod.SupervisorClient()
    out = client.ask("status?")
    assert "model offline" in out.lower()


def test_client_degrades_on_malformed_router_response(monkeypatch):
    # A REACHABLE router that returns a 200 with an error-shaped body (no `choices`)
    # must still not raise into the operator's turn — chat() degrades the KeyError/
    # IndexError/JSONDecodeError into a marker, same contract as a dead socket.
    from loki.supervisor.client import SupervisorClient
    import loki.supervisor.client as client_mod
    monkeypatch.setattr(client_mod.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp({"error": "model_not_found"}))
    out = SupervisorClient().chat([{"role": "user", "content": "status?"}])
    assert "unparseable response" in out.lower()
    assert "no action was taken" in out.lower()


def test_build_messages_grounds_the_turn():
    from loki.supervisor.client import SupervisorClient
    client = SupervisorClient()
    msgs = client.build_messages("what is our VRAM headroom?")
    assert msgs[0]["role"] == "system"          # system prompt
    assert "Loki" in msgs[0]["content"]
    assert msgs[1]["role"] == "system"          # grounded context
    assert "GROUNDED CONTEXT" in msgs[1]["content"]
    assert msgs[2]["role"] == "user"


class _FakeResp:
    """Minimal context-manager stand-in for urllib's urlopen response."""
    def __init__(self, payload: dict):
        import json as _json
        self._body = _json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self._body


def _patch_router(monkeypatch, choice: dict):
    """Make _post_chat see a single-choice response with the given shape."""
    import loki.supervisor.client as client_mod
    monkeypatch.setattr(client_mod.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp({"choices": [choice]}))
    return client_mod.SupervisorClient()


def test_post_chat_surfaces_reasoning_when_content_empty(monkeypatch):
    # A reasoning model that exhausts the token budget leaves content empty but
    # its read-only reasoning in reasoning_content. The client must NEVER return
    # a silent blank — it surfaces the reasoning, marks it as no-action, and
    # flags the truncation.
    client = _patch_router(monkeypatch, {
        "message": {"content": "", "reasoning_content":
                    "I have no shell access and cannot edit that file."},
        "finish_reason": "length",
    })
    out = client._post_chat([{"role": "user", "content": "edit the script"}])
    assert "no shell access" in out                  # reasoning surfaced
    assert "NO action" in out                         # marked read-only/no-action
    assert "max_tokens" in out                        # truncation flagged
    assert out.strip()                                # never blank


def test_post_chat_flags_empty_response_with_no_reasoning(monkeypatch):
    # No content and no reasoning either: still never blank — emit an explicit
    # marker so the operator knows the turn was empty, not that a stance was held.
    client = _patch_router(monkeypatch, {
        "message": {"content": "  ", "reasoning_content": ""},
        "finish_reason": "stop",
    })
    out = client._post_chat([{"role": "user", "content": "status?"}])
    assert "empty response" in out.lower()
    assert "No action was taken" in out


def test_post_chat_returns_normal_content_untouched(monkeypatch):
    # The happy path is unchanged: real content passes through, no markers added.
    client = _patch_router(monkeypatch, {
        "message": {"content": "T5 is active per the snapshot."},
        "finish_reason": "stop",
    })
    out = client._post_chat([{"role": "user", "content": "is T5 up?"}])
    assert out == "T5 is active per the snapshot."


def test_post_chat_suppresses_thinking_by_default(monkeypatch):
    # The supervisor must ask the backend to skip chain-of-thought (it wants a
    # grounded answer, not 3000 reasoning tokens that stall T1's single slot).
    # Capture the outgoing payload and assert the enable_thinking=False switch.
    import json as _json
    import loki.supervisor.client as client_mod
    captured = {}

    def fake_urlopen(req, *a, **k):
        captured["body"] = _json.loads(req.data.decode())
        return _FakeResp({"choices": [
            {"message": {"content": "ok"}, "finish_reason": "stop"}]})

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", fake_urlopen)
    client_mod.SupervisorClient()._post_chat([{"role": "user", "content": "hi"}])
    assert captured["body"]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


# ── supervisor-vs-deterministic conflict boundary (authority gate) ──────────────
# These encode the safety contract in code: an LLM-origin proposal can never
# inherit a rule's earned autonomy, can never auto-fire on a veto window, and can
# never move (or reset) the N=12 trust ladder.
from datetime import datetime, timezone

from loki.authority import AuthorityGate, AuthorityLedger
from loki.schema import ActionRecord, ActionTier, ProposedAction


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeStore:
    """Minimal store: collects emitted events; snapshot() must not be reached on
    the supervisor-floor path (origin floor returns before the flapping check)."""
    def __init__(self) -> None:
        self.events = []

    def emit(self, **kwargs) -> None:
        self.events.append(kwargs)

    def snapshot(self):
        raise AssertionError("classify() must not snapshot on the supervisor floor path")


def _gate_with(action_id, tier, *, clean=0, target=ActionTier.TIER_2):
    led = AuthorityLedger()
    led.records[action_id] = ActionRecord(
        action_id=action_id, current_tier=tier, target_tier=target,
        clean_run_count=clean,
    )
    return AuthorityGate(_FakeStore(), led), led


def _proposed(action_id, *, origin="rule", params=None, dedup=None):
    return ProposedAction(
        action_id=action_id, trigger="t", params=params or {},
        dedup_key=dedup or action_id, rationale="r", proposed_at=_now(),
        origin=origin,
    )


def test_classify_floors_supervisor_origin_even_at_tier2():
    # restore_t1_reasoning sits at Tier 2 (autonomous). A rule keeps that earned
    # tier; a supervisor proposal of the SAME action is floored to Tier 3.
    aid = "restore_t1_reasoning"
    gate, _ = _gate_with(aid, ActionTier.TIER_2, target=ActionTier.TIER_2)
    assert gate.classify(_proposed(aid)) == ActionTier.TIER_2                # rule
    assert gate.classify(_proposed(aid, origin="supervisor",
                                   dedup=f"supervisor:{aid}")) == ActionTier.TIER_3


def test_supervisor_offload_ask_is_blocking_with_no_veto_window():
    # offload_t1_reasoning declares a 120s non-blocking veto window for the rule
    # path. Proposed by the supervisor it must become a BLOCKING ask (no deadline)
    # so the LLM can never trigger a default-proceed.
    aid = "offload_t1_reasoning"
    gate, _ = _gate_with(aid, ActionTier.TIER_3, target=ActionTier.TIER_3)
    dedup = f"supervisor:{aid}"
    gate.dispatch(_proposed(aid, origin="supervisor", dedup=dedup))
    ask = gate.pending[dedup]
    assert ask.blocking is True
    assert ask.expires_at is None
    assert ask.origin == "supervisor"
    # blocking ask => no veto-window-open event emitted
    assert not any(e.get("type") == "action_veto_window_open" for e in gate.store.events)


def test_evict_rule_ask_is_nonblocking_with_veto_window():
    # §10.3 eviction is autonomous-with-veto: a RULE-origin dispatch at cold-start
    # Tier-3 surfaces a NON-blocking ask with a veto deadline (default-proceeds),
    # mirroring offload_t1 — the "prevent while away" + "veto when present" posture.
    aid = "evict_idle_burst_tier"
    gate, _ = _gate_with(aid, ActionTier.TIER_3, target=ActionTier.TIER_2)
    dedup = f"{aid}:t2"
    gate.dispatch(_proposed(aid, params={"tier": "t2"}, dedup=dedup))
    ask = gate.pending[dedup]
    assert ask.blocking is False
    assert ask.expires_at is not None
    assert any(e.get("type") == "action_veto_window_open" for e in gate.store.events)


def test_supervisor_outcome_never_touches_trust_ladder(monkeypatch, tmp_path):
    monkeypatch.setattr("loki.authority.AUTHORITY_PATH", tmp_path / "authority.json")
    aid = "auto_restart_cpu_dataplane_tier"
    gate, led = _gate_with(aid, ActionTier.TIER_3, clean=5)
    sup = _proposed(aid, origin="supervisor", params={"tier": "t3"},
                    dedup=f"supervisor:{aid}")
    gate._finished.append((sup, "approved", "ok"))      # a clean supervisor run
    gate.collect_finished()
    assert led.get(aid).clean_run_count == 5            # earned NOTHING toward N=12
    gate._finished.append((sup, "approved", "failed"))  # a failed supervisor run
    gate.collect_finished()
    assert led.get(aid).clean_run_count == 5            # and reset NOTHING


def test_rule_outcome_still_advances_trust_ladder(monkeypatch, tmp_path):
    monkeypatch.setattr("loki.authority.AUTHORITY_PATH", tmp_path / "authority.json")
    aid = "auto_restart_cpu_dataplane_tier"
    gate, led = _gate_with(aid, ActionTier.TIER_3, clean=5)
    led.save()   # persist the precondition: record() now does an atomic
                 # read-modify-write against disk (cross-process lock), exactly
                 # as the engine does after its per-tick load(), so the primed
                 # clean-run count must be durable, not in-memory-only.
    rule = _proposed(aid, params={"tier": "t3"}, dedup=f"{aid}:t3")
    gate._finished.append((rule, "tier2", "ok"))
    gate.collect_finished()
    assert led.get(aid).clean_run_count == 6            # the rule path still earns trust
