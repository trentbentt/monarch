"""Command Center backend configuration.

All knobs are env-overridable (prefix ``CC_``) so the same code serves dev
(fixture state.json) and prod (live Loki state.json) without edits.
"""
from __future__ import annotations

import os
from pathlib import Path

_HOME = Path.home()


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


# --- The spine: Loki state.json -------------------------------------------
# Prod default is the live daemon state; tests/dev override via CC_STATE_PATH.
STATE_PATH = Path(_env("CC_STATE_PATH", str(_HOME / ".local/state/loki/state.json")))

# How often the watcher re-stats the file (seconds). state.json rewrites ~10s.
STATE_POLL_SEC = float(_env("CC_STATE_POLL_SEC", "2.0"))

# --- loki-q CLI ------------------------------------------------------------
LOKIQ_BIN = _env("CC_LOKIQ_BIN", str(_HOME / "bin/loki-q"))

# --- Bind / network ----------------------------------------------------------
# Loopback ONLY. Tailscale provides the sole remote path; never bind 0.0.0.0.
BIND_HOST = _env("CC_BIND_HOST", "127.0.0.1")
BIND_PORT = int(_env("CC_BIND_PORT", "8780"))

# --- Upstream bearer-keyed services (reached SERVER-SIDE only) ---------------
# Keys are read from the operator's existing env file, never shipped to the browser.
API_KEYS_ENV = Path(_env("CC_API_KEYS_ENV", str(_HOME / ".config/inference/api_keys.env")))
HERMES_URL = _env("CC_HERMES_URL", "http://127.0.0.1:8642")
LITELLM_URL = _env("CC_LITELLM_URL", "http://127.0.0.1:4000")
N8N_URL = _env("CC_N8N_URL", "http://127.0.0.1:5678")
EVERCORE_URL = _env("CC_EVERCORE_URL", "http://127.0.0.1:1995")

# --- Phase 2 legibility sources ---------------------------------------------
# Filesystem stores loki-q reads directly (we mirror, not parse CLI text).
SKILL_DRAFTS_DIR = Path(_env("CC_SKILL_DRAFTS_DIR", str(_HOME / ".hermes/skill-drafts")))
GC_PROPOSALS_DIR = Path(_env("CC_GC_PROPOSALS_DIR", str(_HOME / ".hermes/gc-proposals")))
STALE_DAYS = int(_env("CC_STALE_DAYS", "30"))      # mirrors memory.py / loki-q

# L6 vault — the docs-router search corpus (Truth docs only; see vault README).
VAULT_DIR = Path(_env("CC_VAULT_DIR", str(_HOME / "vault")))

# Loki tree — where supervisor_bridge / retrieval_bridge import the read-only
# supervisor + memory-retrieval layers from. Defaults to the IN-REPO loki/ (this
# monorepo is self-contained: a fresh clone resolves without the operator's
# ~/projects/loki, and the bridges import the same tree the contract validates and
# the daemon runs — review H10). Override with CC_LOKI_ROOT for a split layout.
# Both bridges import THIS constant so there is one source of truth, not three.
LOKI_ROOT = Path(_env("CC_LOKI_ROOT", str(Path(__file__).resolve().parents[2] / "loki")))

# --- Workflows live reader (spec 4 — DORMANT until set) ----------------------
# Read-only DSNs for the news-pipeline + evidence-layer tables, pointing at a
# dedicated SELECT-only `cc_reader` role. UNSET by default: the Workflows
# deep-dive then reports via status.json only (no DB coupling). Server-side
# only — never serialized to the browser. CC_EVIDENCE_DB_URL defaults to the
# workflows DSN when the ev_* tables share that database.
WORKFLOWS_DB_URL = _env("CC_WORKFLOWS_DB_URL", "")     # "" => dormant
EVIDENCE_DB_URL = _env("CC_EVIDENCE_DB_URL", "")       # "" => fall back to workflows

# --- Runtime / audit ---------------------------------------------------------
RUNTIME_DIR = Path(_env("CC_RUNTIME_DIR", str(Path(__file__).parent / "runtime")))
AUDIT_LOG = Path(_env("CC_AUDIT_LOG", str(RUNTIME_DIR / "control.audit.log")))
# Bound the append-only audit log: a denied (unauthenticated) control attempt is
# still recorded, so without a cap a flood of probes could exhaust disk. Rotate to
# a single .1 backup past this size — disk stays bounded at ~2x (review: audit-log
# amplification).
AUDIT_LOG_MAX_BYTES = int(_env("CC_AUDIT_LOG_MAX_BYTES", str(5_000_000)))

# --- Phase 3: control surface (gated) ---------------------------------------
# Operator control token. If unset, a token is generated on first use and
# persisted to CONTROL_TOKEN_PATH (logged once at startup for the operator).
CONTROL_TOKEN = _env("CC_CONTROL_TOKEN", "")            # "" => generate+persist
CONTROL_TOKEN_PATH = Path(_env("CC_CONTROL_TOKEN_PATH", str(RUNTIME_DIR / "control_token.txt")))
# Global dry-run: when true, control actions are NOT executed — they report the
# command they WOULD run. Per-request {"dry_run": true} can also force this on.
CONTROL_DRY_RUN = _env("CC_CONTROL_DRY_RUN", "0") in ("1", "true", "True", "yes")
# Defense-in-depth: when true, the sensitive READ surface (full state, vault
# doctrine, deep-dives, the GPU-spinning supervisor) also requires the control
# token — not just mutations. Default off keeps the tailnet as the read trust
# boundary; flip on to require the token for the whole sensitive surface (the
# client sends it automatically when one is set).
REQUIRE_TOKEN_FOR_READS = _env("CC_REQUIRE_TOKEN_FOR_READS", "0") in ("1", "true", "True", "yes")
# Actuator scripts (idempotent partial-offload / restore — §10.3).
T1_OFFLOAD_BIN = _env("CC_T1_OFFLOAD_BIN", str(_HOME / "bin/t1-offload"))
T1_RESTORE_BIN = _env("CC_T1_RESTORE_BIN", str(_HOME / "bin/t1-restore"))
# n8n workflow trigger allow-list: JSON object {name: "webhook/path"} (empty by
# default — operator opts specific workflows in). Closed enum, no arbitrary URLs.
import json as _json  # noqa: E402
try:
    WORKFLOWS = _json.loads(_env("CC_WORKFLOWS", "{}"))
except ValueError:
    WORKFLOWS = {}
# Local event-ack store (no external effect).
ACK_STORE_PATH = Path(_env("CC_ACK_STORE_PATH", str(RUNTIME_DIR / "acked_events.json")))

# --- Web Push (VAPID) --------------------------------------------------------
PUSH_KEYS_PATH = Path(_env("CC_PUSH_KEYS_PATH", str(RUNTIME_DIR / "vapid_keys.json")))
PUSH_SUBS_PATH = Path(_env("CC_PUSH_SUBS_PATH", str(RUNTIME_DIR / "push_subscriptions.json")))
# Cap stored Web Push subscriptions. Registration is unauthenticated (any tailnet
# peer), so without a bound the store grows without limit. Keep the most-recent N;
# older entries are dropped FIFO (review: unbounded push subscription writes).
PUSH_MAX_SUBS = int(_env("CC_PUSH_MAX_SUBS", "50"))
# Contact mailto: for VAPID claims (push services require a contact).
PUSH_CONTACT = _env("CC_PUSH_CONTACT", "mailto:admin@example.com")
# Interrupt-class event types that bypass overnight quieting (doctrine §9.5.3).
PUSH_INTERRUPT_TYPES = set(
    _env(
        "CC_PUSH_INTERRUPT_TYPES",
        "gpu_thermal_critical,security_alert,spend_burst,ram_exhaustion",
    ).split(",")
)
