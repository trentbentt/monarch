# Loki Supervisor — read-and-propose conversational layer

The supervisor sits **above** the deterministic Loki daemon. It reads live
state, the authority ledger, and doctrine (all read-only), answers the operator
in natural language, and — when warranted — submits proposals into the daemon's
existing `AuthorityGate`. It holds **no authority of its own**: every proposal it
makes is classified and operator-gated through that gate, and — because it is an
LLM, not a deterministic rule — held to a *stricter* floor: every supervisor
proposal surfaces as a **blocking Tier-3 ask** and never moves the N=12 trust
ladder (`master_summary §9.5` authority model / `§12.6` decision-engine flow).

This is the one place in the monarch stack where a CLAUDE-FABLE-5-style system
prompt belongs. Loki itself is a deterministic control daemon with no prompt
surface; the stack's actual prompting lives in the ~18 `CLAUDE.md` files. The
supervisor is the LLM component, and `system_prompt.md` is its prompt.

## Why it can get smarter without getting more dangerous

The daemon's safety is one invariant: every action is born at Tier 3
(surface-and-ask) and earns autonomy only through the N=12 trust ladder, which the
operator approves at every step. The supervisor is an additional **proposal
source**, never an additional **authority** — so adding intelligence on top adds
no risk. The boundary is enforced in code, not just in the prompt:

| Guarantee | Where it's enforced |
|---|---|
| Reads state/ledger/doctrine read-only (never writes them) | `context.py` (uses `StateStore.load_from_disk()` + direct file reads) |
| Can only propose actions that actually exist | `proposals.py` validates `action_id ∈ ACTIONS` at **submit** and again at **drain** |
| Can never inherit a rule's earned autonomy | `authority.py` `classify()` floors every non-rule origin to **Tier-3 blocking** — always an explicit-approval ask, never a Tier-1/2 auto-fire and never a veto-window default-proceed |
| Can never move (or reset) the N=12 trust ladder | `authority.py` `collect_finished()` records outcomes only for `origin == "rule"` — a supervisor run earns no promotion trust and a failed one resets no streak |
| Provenance can't be forged | `proposals.py` `drain()` re-stamps `origin = "supervisor"` on every entry, so a hand-edited queue file can't pose as a rule |
| Wiring it in changes nothing until you say so | engine intake is **default-off** behind `LOKI_SUPERVISOR_PROPOSALS`, with a defensive import |
| One-shot asks persist until you decide | `engine.py` keeps non-rule-origin asks in the prune active-set and exempts them from rule cooldown; approve or veto clears them (they never default-proceed) |
| A model outage never blocks the daemon | `client.py` degrades gracefully; the daemon does not depend on the LLM being up |

## Files

```
loki/supervisor/
  system_prompt.md   ← the LLM system prompt (failure-mode-anchored "Fable" style)
  context.py         ← READ-ONLY grounding: state.json + authority.json + query-directed retrieval
  retrieval.py       ← READ-ONLY memory-layer retrieval (L3/L4/L5/L6/L7) + §8.6 router (Phase A)
  agent.py           ← Phase B: read-only model-driven multi-step retrieval loop (ReAct)
  proposals.py       ← the ONLY write path; writes validated *requests* to the queue file
  client.py          ← routes the turn through LiteLLM:4000 (no API key); graceful offline
  tests/             ← safety-boundary + retrieval + agent-loop tests (50 total)
bin/loki-supervisor ← operator CLI (ask / context / actions / propose / queue)
```

## Memory retrieval (Phase A — query-directed injection)

`ask` is now grounded in the **memory architecture**, not a 4 KB doctrine head-
excerpt. For each question, `retrieval.gather()` deterministically routes to the
right layers (the `final_memory_architecture.md` §8.6 verb heuristic — no model
call) and injects a provenance-tagged `## retrieved_context` block the model must
cite:

| Layer | Source | How |
|---|---|---|
| **L3** | embedded vault (`vault_note_chunks`) | nomic `search_query:` embed → pgvector `<->` nearest-k |
| **L4** | Hermes session history | `state.db` FTS5, opened **read-only** (`mode=ro&immutable=1`) |
| **L5** | indexed code graph | `codebase-memory-mcp cli search_code` |
| **L6** | doctrine sections | section-addressed fetch — an explicit `§N.N` in the question is pulled in full and **prioritized over fuzzy hits** under budget |
| **L7** | EverCore long-horizon | `:1995/api/v1/memories/search` |

Every backend is isolated: a down layer becomes a `_retrieval note_`, never a
broken turn. The block is bounded by `LOKI_SUPERVISOR_RETRIEVAL_BUDGET` (char
proxy for tokens). Retrieval is **read-only by construction** (SELECT / ro-SQLite
/ GET / read CLI) — it widens what the supervisor *knows*, never what it can *do*.

## Memory retrieval (Phase B — model-driven agentic loop, `--deep`)

`ask --deep` lets the model **drive** retrieval over multiple steps instead of one
deterministic pass: it reads, decides what to pull, sees the result, and pulls
again — chasing a thread (doctrine → live state → answer). Uses a deterministic
**ReAct text protocol** (`RETRIEVE: {json}` / prose answer), not llama.cpp native
tool-calling, so it is model-agnostic and fully testable.

Safety + robustness (all in `agent.py`, asserted in tests):

| Property | How |
|---|---|
| **read-only** | the loop's tool registry is *exactly* the five retrieval fns; an unknown/forged tool is rejected, never executed. Proposing stays the explicit `propose` path — unreachable from the loop |
| **bounded** | ≤ `LOKI_SUPERVISOR_MAX_STEPS` retrieval rounds, then a forced answer — always terminates |
| **anti-thrash** | a duplicate `(tool,args)` is not re-run; the model is told it already has it |
| **on-mission** | the operator's verbatim question is re-anchored every step (§8.7 principle; no parallel store, §14) |
| **always answers** | the final synthesis call drops the retrieval affordance and answers from gathered evidence (Phase-A behavior the local 27B handles reliably) — a raw `RETRIEVE` directive is never surfaced |
| **degrades** | a tool error becomes feedback, never an exception |

Phase A (default `ask`) stays the fast single-shot path; `--deep` is opt-in for
genuine multi-step investigation. Persistent cross-`ask` conversation memory (with
the §8.7 Hermes compressor) remains deferred — it would route through Hermes, not a
new store (§14).

## Operator CLI

```bash
loki-supervisor ask "why did T1 offload last night?"
loki-supervisor ask --memory "explain our memory layers"   # inline memory doctrine
loki-supervisor ask --deep "trace how a vault edit reaches L3 search"  # Phase B agentic loop
loki-supervisor context                                    # dump grounded context (no model call)
loki-supervisor actions                                    # list the proposable actions
loki-supervisor propose <action_id> "rationale" --param tier=t5
loki-supervisor queue                                      # peek pending proposals
```

`propose` enqueues regardless of whether intake is enabled; the engine only drains
the queue when the daemon runs with intake on (below).

## Enabling it (default-off; nothing is auto-enabled)

Two deliberate steps, whenever the operator wants the layer live:

1. **Proposal intake** — restart the daemon with `LOKI_SUPERVISOR_PROPOSALS=1`.
   Until then `propose` enqueues but the engine never drains it; the running
   daemon is byte-for-byte unaffected. `deploy.sh` passes this var through from
   its own environment, so the deliberate way to bring the daemon up live is:

   ```bash
   inference-up                                  # control session + LiteLLM:4000 + tiers
   cd ~/projects/loki && LOKI_SUPERVISOR_PROPOSALS=1 ./deploy.sh
   ```

   A bare `./deploy.sh` launches with the var unset → intake stays OFF. The flag
   is never hardcoded; default-off is preserved.
2. **Conversational `ask`** — bring up LiteLLM on port 4000 (already up after
   `inference-up`). Until then `ask` returns the assembled grounded context plus
   a clear "model offline" note.

## Configuration (environment)

| Var | Default | Purpose |
|---|---|---|
| `LOKI_SUPERVISOR_PROPOSALS` | unset (off) | enable engine intake of supervisor proposals |
| `LOKI_SUPERVISOR_QUEUE` | `~/.local/state/loki/supervisor_proposals.json` | proposal queue file |
| `LOKI_SUPERVISOR_LLM_BASE` | `http://localhost:4000/v1` | LiteLLM router base URL |
| `LOKI_SUPERVISOR_MODEL` | `qwen3.6-consultancy` | routable model_name (local T1 by default; on-box, no cloud key) |
| `LOKI_SUPERVISOR_TIMEOUT` | `60` | LLM request timeout (seconds) |
| `LOKI_SUPERVISOR_MAX_TOKENS` | `2500` | response budget; raise for reasoning models that emit long `reasoning_content` |
| `LOKI_SUPERVISOR_THINKING` | `0` (off) | set `1` to allow chain-of-thought; off keeps answers fast and frees T1's slot |
| `LOKI_SUPERVISOR_RETRIEVAL_BUDGET` | `8000` | char budget for the injected `## retrieved_context` block (proxy for tokens) |
| `LOKI_SUPERVISOR_L5_PROJECT` | `home-operator-projects-loki` | codebase-memory project for L5 `search_code` |
| `LOKI_SUPERVISOR_L7_USER` | `monarch` | EverCore `user_id` filter for L7 search |
| `LOKI_SUPERVISOR_MAX_STEPS` | `3` | Phase B (`--deep`) max model-driven retrieval rounds before forced synthesis |

> Latency note: retrieval enlarges the grounded turn, so prefill on T1's single
> 27B slot takes longer. A bigger ctx window does **not** help (the turn is prompt,
> not an empty buffer); tune `LOKI_SUPERVISOR_RETRIEVAL_BUDGET` down and/or
> `LOKI_SUPERVISOR_TIMEOUT` up if a deep question stalls.

> The router requires auth: the client presents `LITELLM_MASTER_KEY` (sourced from
> `~/.config/inference/api_keys.env`). A bare shell that hasn't sourced that file
> will get "model offline" — source it (or run from the daemon's environment).

## Tests

```bash
~/venv/inference/bin/python3 -m pytest loki/supervisor/tests -q
```

Covers both hallucination-defense layers, read-only context assembly (including
the no-state case), graceful offline degradation, and turn grounding. The engine
integration (proposal → tick → gate Tier-3 ask, and survival across a no-condition
tick) is verified in the build smoke; see the build commit.
