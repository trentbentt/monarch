# Loki — autonomous supervisor for a self-hosted, multi-tier LLM stack

Loki is the always-on brain that runs a personal AI infrastructure on a **single
workstation GPU**. It keeps a fleet of local language models co-resident in
limited VRAM, routes work to the right model, manages memory pressure as an
intensity *cascade* rather than a binary on/off, and proposes (never silently
takes) corrective action through a gated authority model.

> **About this repository.** This is the **public architecture skeleton** of a
> larger private system. It documents the design and engineering; live
> operational detail (hosts, addresses, credentials, runbooks) lives in private
> repositories and never appears here. See *Memory Architecture* below for the
> companion design doc.

---

## The forcing function

Most "AI infrastructure" assumes elastic cloud capacity. This system assumes the
opposite: one 24 GB consumer GPU, always on, expected to serve a reasoning model,
a pipeline burst model, utility models, and an optional coder model — **at the
same time**. That constraint is the entire design driver. It forces three things
that turn out to be the interesting engineering:

1. **Weight sharing** so multiple tiers physically fit.
2. **A pressure cascade** so the system degrades gracefully instead of OOM-ing.
3. **An autonomous supervisor** so a human isn't in the loop for routine pressure
   management — but *is* the final authority on anything risky.

---

## What Loki is

Loki is a Python daemon: a typed (Pydantic) system model, a queued-write state
store, and a set of listener threads that continuously observe the inference
stack and its dependencies. On top of that substrate sit a **decision engine**
(deterministic rules) and an optional **supervisor layer** (a local LLM that
reads state and *proposes* actions in natural language).

Its job description, in four questions it must always be able to answer:

- **What is running, and is it healthy?** (observability)
- **Is the system under pressure, and where?** (VRAM, quota, process, cron, memory)
- **What should change, and is that change safe to make autonomously?** (decisions + authority)
- **Can it explain any of the above?** (the documentation/retrieval role)

---

## Architecture

### Substrate (the daemon)
- **System model** — one typed schema describing tiers, services, memory layers,
  quotas, and the decision/authority state. Everything else reads and writes this
  model; serialized snapshots are explicitly *not* a source of truth.
- **Listeners** — independent polling threads: VRAM / OOM risk, tier health
  (probed in parallel), process accounting, cloud-quota budgets, cron schedule,
  the memory layers, and hardware health (GPU thermal, disk SMART, RAM ECC).
- **Decision engine** — deterministic rules that turn observations into proposed
  actions, each tagged with an authority tier.

### Inference stack (tier-by-tier)
A reasoning brain runs always-on; a pipeline-burst model spins up only when work
arrives; utility and helper models run CPU-resident at zero VRAM cost; an optional
coder model is deployed but offline by default. The reason five models fit at all
is **mmap weight sharing** — overlapping weights are mapped, not re-copied, so the
combined footprint stays inside the envelope. Each tier has a measured throughput
and a documented operating point rather than a guess.

### Routing
A router fronts the stack: local-first, with explicit, budgeted cloud-fallback
rungs and a validation gate. What goes through the router vs. direct-to-tier is a
deliberate, documented split, not an accident of convenience.

### VRAM pressure as a cascade
Rather than "evict everything when full," pressure is a **continuous intensity
band**. As pressure rises, Loki offloads, hot-swaps, and — only at the top of the
band, and only when a tier is provably idle — evicts a burst tier. Eviction is
*autonomous-with-veto*: Loki may act without blocking, but the action is
non-blocking, audited, and guarded at execute time by a freshness re-check so it
can never evict work that just became active.

### Authority model (the part that makes autonomy safe)
Every proposed action carries an **authority tier**. Low-stakes actions are
autonomous; risky ones require operator approval; some are autonomous-with-veto
(act now, but observably and reversibly). The model enforces **strict cold-start**:
Loki earns trust through a recorded ledger of outcomes before it is allowed to act
unsupervised on a given class of action. Concurrency on that ledger is hardened
with cross-process atomic read-modify-write so trust accounting can't race.

### Supervisor layer (read-and-propose)
Above the deterministic engine sits an optional LLM supervisor: it reads system
state and the memory layers, and emits natural-language proposals. It is
**default-off, gated, and forbidden from coaching a gate bypass**. It can retrieve
from the memory architecture (including doctrine) to ground its proposals, but it
never executes — it proposes, the authority model decides.

### Voice (operator surface)
A wake-word front end (openWakeWord) plus local STT and TTS gives a hands-free,
conversational way to ask the system what it's doing — built on top of the
read-and-propose supervisor, so speaking to it carries the same safety contract as
everything else.

---

## Memory Architecture

Loki is the **Arbiter** of a seven-component memory system that collapses to four
conceptual roles under a single conflict-resolution rule. The full design — Truth
/ Index / Memory / Arbiter, the per-layer detail, the routing table, authority
gating for memory writes, and per-layer failure/recovery — is documented in:

**[`docs/MEMORY_ARCHITECTURE.md`](docs/MEMORY_ARCHITECTURE.md)**

The one-paragraph version: hot operational state, structured relational data,
human-curated knowledge, and repositories are all **Truth** in different shapes;
semantic vectors, a code-structure graph, and session search are all **Index**; an
agent working-memory layer and a long-horizon temporal store are both **Memory**.
Loki is the only **Arbiter** — a pure router and observer with no authoritative
knowledge of its own. When sources disagree, Truth wins.

---

## Engineering discipline

This system is **doctrine-driven**: a single canonical document is the source of
truth, every claim about code names the file it was reconciled against, and a
nightly lint reconciles doctrine against the live code so drift can't accumulate
silently. Features ship test-first; risky changes are gated; nothing about the
architecture is asserted without a measured number or a commit reference behind
it. That discipline is the real product — the models are interchangeable.

---

## Repository layout

```
loki/                core daemon
  schema.py            typed system model (Pydantic)
  state.py             queued-write state store
  listeners/           vram · tier_health · process · quota · cron · memory · hardware
  rules.py             deterministic decision engine
  actions/             enumerated, authority-tagged actions
  authority.py         trust ledger + cold-start gating
  supervisor/          read-and-propose LLM layer (default-off)
  voice/               wake-word + STT/TTS operator surface
bin/                 loki-q (state query CLI) · loki-supervisor · loki-voice
docs/                MEMORY_ARCHITECTURE.md + design specs
```

## Status

Substrate, listeners, decision engine, VRAM pressure cascade (incl. burst-tier
eviction), authority model, read-and-propose supervisor, and the voice surface are
**built and tested**. This public skeleton tracks the architecture; operational
go-live state is managed privately.
