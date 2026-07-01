# Command Center PWA

A human-friendly dashboard over the monarch infrastructure — Loki substrate,
the 7-layer memory architecture, inference tiers, workflows, routing, authority,
and spend. Installable PWA reachable at the desk (loopback) and on the phone
(Tailscale). Sends Web Push for interrupt-class events. Phase 3 adds a gated
control surface.

This is doctrine's **"Command Center PWA (Phase 19)"** (`final_master_summary.md`
E12), pulled forward.

## Layout

```
server/          FastAPI backend (dedicated venv; binds 127.0.0.1 only)
  config.py        settings (paths, ports, bind addr)
  models.py        DERIVED contract types only (Overview/status rollups)
  derive.py        rollup logic: raw state.json -> Overview
  reader/          state.json watcher, loki-q wrappers, service proxies
  api/             read-only REST + SSE  (Phase 1)
  control/         enumerated POST actions + audit log  (Phase 3)
  push/            VAPID Web Push, overnight-window aware  (Phase 2/3)
  tests/           pytest against a fixture state.json (no live daemon)
web/             React + Vite PWA (minimal phone face / rich desktop face)
scripts/         make_fixture.py (sanitised real state.json -> test fixture)
docs/            design + specs
```

## Design principle

Loki owns the state schema (`~/projects/loki/loki/schema.py`). This backend
does **not** re-declare those models — it passes domain dicts through and adds a
thin derived `Overview`. The spine is `~/.local/state/loki/state.json`
(rewritten every 10s); `loki-q` is the secondary surface.

## Security

Browser talks only to FastAPI. Bearer-keyed services (Hermes, LiteLLM, n8n,
EverCore) are reached server-side only. Backend binds `127.0.0.1`; Tailscale is
the sole remote path. Control actions are a closed enum (no arbitrary commands),
each audit-logged.

## Quick start (dev)

```bash
cd server
python3 -m venv ~/venv/command-center          # dedicated venv, NOT ~/venv/inference
~/venv/command-center/bin/pip install -r requirements.txt
CC_STATE_PATH=tests/fixtures/state.sample.json \
  ~/venv/command-center/bin/uvicorn main:app --host 127.0.0.1 --port 8770
```
