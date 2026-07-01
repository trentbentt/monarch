# Architecture — one organism

The projects in this repository are not four applications that talk to each
other. They share one body, and each tier is built on the one below it.

## The shared substrate

- **One GPU.** A single 24 GB card hosts the tiered model stack. Everything
  downstream is shaped by that budget.
- **One vector store.** A pgvector Postgres holds the semantic index of the
  doctrine corpus plus cost accounting.
- **One working memory.** A Redis instance is the hot operational layer.

These aren't four services that integrate — they're one runtime with several
faces.

## The layered control plane

```
            operator
               │
        Command Center            (PWA + Tauri desktop)
        REST/SSE reads · audited control surface
               │  loki-q CLI · direct retrieval imports · state.json
               ▼
             Loki                 (daemon + supervisor)
        listeners → rules → authority gate → actions
               │  doctrine retrieval (pgvector)
               ▼
            doctrine              (the Truth corpus)
```

Each tier consumes the one beneath it: the Command Center reads Loki three ways
(it shells the `loki-q` CLI, imports Loki's retrieval layer directly, and reads
the daemon's `state.json`); Loki grounds its supervisor on the doctrine corpus.

## The authority model

Loki is allowed to act, but autonomy is *earned*, never assumed:

- Every action is classified into a tier. Tier 1 acts silently, Tier 2 acts and
  logs, Tier 3 surfaces a request and waits for explicit operator approval.
- After N clean runs below its target tier, an action becomes *eligible* for
  promotion — but the engine never self-promotes; promotion is always an
  operator decision.
- The trust ledger is the durable spine. It is written from two separate
  processes (the long-lived daemon and the short-lived CLI), so every mutation
  is a cross-process atomic read-modify-write under an advisory lock. A stale
  in-memory writer can never clobber a committed decision.

## Why `contracts/`

The integration above was real but, before consolidation, guarded only by
*convention*: each side hand-coded its own copy of the shared field names.

The clearest proof is a bug. The authority ledger is **written** by the daemon
as `clean_run_count` / `state`, but the supervisor **read** it as `clean_runs` /
`lifecycle` — names that never existed on disk. So the supervisor's grounded
trust block was silently always null: it confabulated trust state in exactly the
place it was supposed to cite it. Two halves of the *same service* disagreed on
their own schema, and nothing caught it, because there was no shared schema and
no test that crossed the boundary.

`contracts/` is the fix:

- `contracts/ledger.py` — the canonical authority-ledger field set, and the two
  trust fields the supervisor grounds on.
- `contracts/state.py` — the `state.json` domains the Command Center reads.
- `contracts/tests/test_conformance.py` — imports the *live* writer and reader
  and asserts both agree with the contract. It fails loudly the moment any
  producer or consumer drifts. This is the test the seam never had.

The lesson generalizes: integration that is real but unguarded is a latent
outage. Making the contract explicit — and testing across the boundary — is
what turns a pile of cooperating processes into one system you can trust.
