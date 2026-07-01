# Memory Architecture

The system's memory is not one database. It's seven addressable components that
collapse to **four conceptual roles** under **one conflict-resolution rule**, with
Loki as the only arbiter. This document is the public design overview; live
endpoints, schemas, and credentials live in private repositories.

> **About this document.** Public architecture skeleton. It names off-the-shelf
> technologies and the roles they play; it deliberately omits hosts, addresses,
> ports, and any operational secret.

---

## Why this is treated as load-bearing

In agentic work, memory failures don't show up as quality regressions — they show
up as *wrong actions taken confidently*. A decision built on stale operational
state, an agent procedure that has drifted from its source note, code knowledge
that's gone stale between a semantic index and a structure graph — these cause
real, expensive mistakes, not retries. So memory gets the same doctrinal rigor as
the inference stack.

---

## The four roles

The seven-technology landscape collapses to four roles under an "elegance test":

| Role | What it is | Rule |
|---|---|---|
| **Truth** | Authoritative current state and curated knowledge | Canonical; everything else defers to it |
| **Index** | Fast ways to *find* things in Truth | Derived; rebuildable; never authoritative |
| **Memory** | Working and long-horizon recall for agents | May be stale; reconciles against Truth |
| **Arbiter** | The router/observer that decides where a question goes | Holds no knowledge of its own |

Several technologies share a role — relational data, hot state, repositories, and
human-curated notes are all *Truth in different shapes*; vectors, a code-structure
graph, and session search are all *Index*; a working-memory agent and a
long-horizon store are both *Memory*. **Loki is the only Arbiter.** Seven
components, four roles, one rule.

---

## The single conflict-resolution rule

**When two layers disagree, Truth wins; Index and Memory are reconciled to it,
never the reverse.** An Index that disagrees with Truth is stale and must be
re-derived. A Memory layer that disagrees with Truth is out of date and must be
refreshed. This one rule is what keeps seven moving parts from becoming seven
competing opinions.

The test for *any* future addition: name its role, and name what it reconciles
against. If it can't be placed, it doesn't get added.

---

## The seven layers

| Layer | Technology | Role |
|---|---|---|
| **L1** | In-memory key/value store | Truth — hot operational state (sub-10 ms) |
| **L2** | Relational database | Truth — structured relational records |
| **L3** | Vector index over L2/L6/code | Index — semantic search |
| **L4** | Agent working memory (files + session store) | Memory — short-horizon, in-session |
| **L5** | Code-structure graph (MCP) | Index — "what calls what" / structural |
| **L6** | Human-curated knowledge vault | Truth — durable, hand-authored knowledge |
| **L7** | Long-horizon temporal store | Memory — time-bounded inference over history |

A few design notes that matter:

- **L6 is curated, not comprehensive.** The vault's value is being a *high-quality*
  knowledge graph. Capture conventions that lower friction at the cost of
  accumulating low-quality content are rejected — because garbage in L6 gets
  embedded by L3, surfaced to agents, and then treated as Truth, silently
  degrading every layer above. Tooling and scratch trees are explicitly excluded
  from the semantic index.
- **Index layers stay fresh automatically.** Committing a vault note triggers an
  incremental re-embed of only the changed notes (content-hashed); the code graph
  re-indexes on repository changes; session search appends per turn.
- **Memory reconciles to Truth.** The working-memory layer keeps fast-path caches
  of operator preferences, but the curated vault is canonical; caches are synced
  from Truth, not the other way around.

---

## Routing

The Arbiter maps a question to the layer that should answer it. A representative
slice:

| Question | Layer | Why |
|---|---|---|
| "What's the current state of X?" | L1 | hot state, sub-10 ms |
| "What's my preference for X?" | L6 (cache in L4) | vault is canonical |
| "What did we discuss last week?" | L4 session search | keyword recall |
| "How do I do X?" (stable procedure) | L4 skill | reusable procedure |
| "What does function X do / who calls it?" | L5 | structural graph |
| "Find code/news similar to X" | L3 | semantic |
| "How has the long-term picture on X evolved?" | L7 | temporal inference |
| "Where's the doc for X?" | L6 | documentation router |

Some routes are runtime arbitration; others are pure configuration (an agent's
tool calls bind directly to a layer with no arbitration needed).

---

## Authority gating for memory writes

Writes to memory are governed by the same authority model as the rest of the
system, on two axes: *which layer* is being written, and *how risky* the write is.
Promoting something into **Truth** (e.g., turning a transient observation into a
curated note, or syncing into operator-facing state) is treated as a high-trust
action and is gated. **Strict cold-start applies**: the system must earn a track
record before it writes to Truth unsupervised. The arbiter observes; it does not
grant itself write authority.

---

## Failure modes and recovery

Each layer has a documented failure mode and recovery path, and — critically — a
defined behavior when it's *down*: the system degrades to the next-best layer
rather than failing the query. Index layers are always rebuildable from Truth, so
their failure is a performance event, not a data-loss event. Memory-layer outages
fall back to Truth. A cascade failure (multiple layers down) degrades to "answer
only from Truth, flag reduced confidence" rather than guessing.

---

## Build sequence (rationale)

The layers were built in dependency order: curated knowledge first (so there's
something worth indexing), then the semantic index over it, then the structural
code graph, then the agent working-memory layer, then the long-horizon store, and
finally the hot-state layer (which joins with the operational pipelines). Each
step had to be useful on its own before the next was added — no layer was built on
the promise of a future one.
