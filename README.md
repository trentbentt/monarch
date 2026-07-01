# monarch

A self-hosted control plane that lets an LLM **propose** actions against a live
GPU/model stack while a deterministic, operator-gated trust ladder decides what
may actually run — so an LLM proposer can never inherit authority it didn't earn.

This is a **curated public skeleton** of a larger private system. It showcases the
architecture and the engineering; hosts, addresses, credentials, and the
operator's environment are deliberately omitted. References like `§9.5` point to
internal doctrine sections that are not part of this public skeleton.

## The system in one paragraph

One box with a single 24 GB GPU runs a **tiered model stack** — an always-on
reasoning tier plus burst and CPU-resident tiers that share weights (mmap) so more
models fit than raw VRAM would suggest. A long-running daemon, **loki**, observes
the stack through listeners, decides with pure-function rules, and acts only
through an **authority ledger**: every action sits on an N=12 trust ladder, and an
LLM "supervisor" can read state and *propose* actions but is structurally floored
to a blocking, operator-gated tier — it never moves the ladder a deterministic
rule climbs. An operator console, **command-center**, gives a read view over
REST/SSE and a closed-enum, audited, token-gated control surface. The pieces share
one substrate and one control plane; **contracts/** makes the seams between them
explicit and tests them.

## The forcing function

A single 24 GB GPU is the constraint the whole design answers to. The tier layout,
weight sharing, burst eviction with an execute-time freshness guard, and the VRAM
pressure cascade all exist because the system must run a real multi-model workload
on one consumer card without thrashing. The constraint is what makes the
engineering non-trivial — it is not incidental.

## Start here — the load-bearing engineering

If you read three things, read these:

- **`loki/loki/authority.py`** — the trust model. An LLM proposal is floored to a
  blocking, operator-gated tier and can never move the N=12 trust ladder a
  deterministic rule climbs. The cross-process authority ledger holds a
  single-writer invariant under an advisory `flock` + atomic `os.replace`, proven
  by a real multiprocessing lost-update test and a Hypothesis property suite over
  the ladder's invariants (`loki/loki/tests/`).
- **`contracts/` + `contracts/tests/test_conformance.py`** — the seam discipline.
  A cross-boundary test that fails loudly when any producer or consumer drifts
  from a shared shape; it reproduces the real drift bug that motivated
  consolidating the stack, and runs in CI on every push.
- **`command-center/server/control/`** — the actuation surface. A closed action
  enum, argv-list subprocess calls (no shell), constant-time token compare, a
  global dry-run, an append-only audit log, and a token read-gate.

## Memory

The system's memory is seven addressable components that collapse to four
conceptual roles under one conflict-resolution rule, with loki as the only
arbiter. See [`loki/docs/MEMORY_ARCHITECTURE.md`](loki/docs/MEMORY_ARCHITECTURE.md)
— a public design overview that names the technologies and the roles they play and
omits all hosts, addresses, and operational secrets.

## Layout

| Path | Role |
|------|------|
| [`loki/`](loki/) | The daemon: listeners → pure-function rules → the authority-ledger trust model → a read-and-propose LLM supervisor. |
| [`command-center/`](command-center/) | The operator console — FastAPI + React PWA + Tauri desktop, Tailscale-gated. Read surface over REST/SSE; an enumerated, audited, token-gated control surface. |
| [`contracts/`](contracts/) | Shared cross-boundary shapes + the conformance tests that enforce them. |
| [`docs/`](docs/) | How the pieces compose into one organism — and the seam bug that motivated `contracts/`. |

## Provenance

The commit history here is a **curated, build-order reconstruction** — it walks
the architecture in dependency order (schema → daemon pipeline → authority trust
model → supervisor → console → contracts → hardening → CI) so the design is legible
to a reader, rather than a single squashed snapshot. It is *not* the literal
development timeline: the real incremental history (many commits over months) lives
in the private true-source monorepo, and working-tree artifacts (models,
`node_modules`, venvs) are deliberately excluded here. Every layer's tests pass at
`HEAD`.

## Tests

CI (`.github/workflows/ci.yml`) runs the cross-boundary conformance suite, the
loki daemon/authority/listener suites, and the Command Center server suite on
every push and pull request. To run the seam guard locally:

```sh
python -m pytest contracts/tests -q
```
