"""
Memory Listener v0.2

Observes the 7-layer monarch memory architecture (MEMORY_ARCHITECTURE §10).
Loki is the Arbiter — it does not own these layers' content; it watches their
health and activity and surfaces drift as events.

Observation strategy per layer (boundaries locked 2026-05-29):
  L1 Redis           read-state   — mirrors the `l1-redis` health component (:6379, LIVE at P1.5-6)
  L2 Postgres        read-state   — mirrors the `postgres` health component (:5432)
  L3 pgvector        PROBE 60s    — SELECT extversion … extname='vector' on the loopback vault DB
  L4 Hermes          PROBE 30s    — HTTP /health (:8642, bearer) + state.db mtime activity
  L5 Codebase-Memory read-state   — mirrors the `codebase-memory` health component
  L6 Obsidian vault  PROBE 300s   — ~/vault writable + `git status` clean
  L7 EverCore        read-state   — mirrors the `evercore` composite component (:1995)

── Design notes ───────────────────────────────────────────────────────────────
- Single listener, per-layer cadences. BaseListener has one interval; we run at
  the finest active cadence (30s, L4) and gate the slower probes (L3 60s, L6
  300s) internally on monotonic deadlines, carrying forward the previous result
  in between.
- state.db mtime is an ACTIVITY signal, not a health gate (mirrors how
  tier_health treats codebase-memory's index mtime) — an idle Hermes is healthy.
- Read-state layers (L2/L5/L7) are NOT re-probed; their signal is mirrored from
  the health components tier_health already maintains, the same non-duplication
  discipline as tier_health ↔ process.
- Events fire on transition only (consistent with vram.py / tier_health.py /
  cron.py): memory_layer_unhealthy, memory_layer_recovered, and
  memory_anomaly_detected (stale skill drafts >30d per §11.4).

Spec: final_memory_architecture.md §10.2; final_master_summary.md §12.4 listener queue.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .base import BaseListener
from ..schema import MONARCH_MEMORY_LAYERS, MemoryLayer, MemoryLayerHealth
from ..state import StateStore

logger = logging.getLogger(__name__)

# Per-layer probe cadences (seconds) for the layers memory.py actively probes.
_CADENCE = {"L3": 60.0, "L4": 30.0, "L6": 300.0}

# L3 pgvector — loopback Postgres; DSN env-overridable (LOKI_PG_*), credentials
# never in source (password loaded from the local monarch-stack env at runtime).
_PG_HOST = os.environ.get("LOKI_PG_HOST", "127.0.0.1")
_PG_PORT = int(os.environ.get("LOKI_PG_PORT", "5433"))
_PG_DB   = os.environ.get("LOKI_PG_DB", "vault")
_PG_USER = os.environ.get("LOKI_PG_USER", "monarch")
_MONARCH_ENV = os.path.expanduser("~/monarch-stack/.env")

# L4 Hermes — gateway on :8642, bearer key in ~/.hermes/.env (API_SERVER_KEY).
_HERMES_HOST, _HERMES_PORT = "127.0.0.1", 8642
_HERMES_ENV = os.path.expanduser("~/.hermes/.env")
_HERMES_STATE_DB = os.path.expanduser("~/.hermes/state.db")

# L6 Obsidian vault.
_VAULT_DIR = os.path.expanduser("~/vault")

# Skill drafts (§8.4 draft-state pattern; §11.4 stale-draft surfacing).
_SKILL_DRAFTS_DIR = os.path.expanduser("~/.hermes/skill-drafts")
_STALE_DRAFT_DAYS = 30

# Curated-tier GC proposals (§8.8 janitor; same draft-state pattern as skill
# drafts — a pile of unreviewed prune/merge proposals is the same stale-backlog
# anomaly). Proposals are one JSON file each in the dir below.
_GC_PROPOSALS_DIR = os.path.expanduser("~/.hermes/gc-proposals")
_STALE_GC_DAYS = 30

# ComponentHealth.status (string value) → MemoryLayerHealth for read-state layers.
_COMPONENT_HEALTH_MAP = {
    "ok":           MemoryLayerHealth.OK,
    "idle":         MemoryLayerHealth.OK,          # cleanly offloaded ≠ broken
    "degraded":     MemoryLayerHealth.DEGRADED,
    "stopped":      MemoryLayerHealth.DEGRADED,
    "unresponsive": MemoryLayerHealth.UNRESPONSIVE,
    "error":        MemoryLayerHealth.UNRESPONSIVE,
    "unknown":      MemoryLayerHealth.UNKNOWN,
}

_UNHEALTHY = {MemoryLayerHealth.UNRESPONSIVE, MemoryLayerHealth.DEGRADED}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _read_env_value(path: str, key: str) -> Optional[str]:
    """Read KEY=value from a dotenv-style file. None if file/key absent."""
    try:
        text = Path(path).read_text()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.M)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'")


def _mtime_age_s(path: str) -> Optional[int]:
    try:
        return int(time.time() - os.path.getmtime(path))
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _fmt_age(secs: Optional[int]) -> str:
    if secs is None:
        return "—"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


# ─── Active probes (memory.py owns these signals) ─────────────────────────────

def _probe_pgvector() -> Tuple[MemoryLayerHealth, str, Optional[str], Optional[int]]:
    """L3 — vector extension present in monarch-postgres/vault. Returns
    (health, health_signal, activity_signal, response_ms)."""
    pw = _read_env_value(_MONARCH_ENV, "MONARCH_POSTGRES_PASSWORD")
    if pw is None:
        return (MemoryLayerHealth.UNKNOWN,
                "no MONARCH_POSTGRES_PASSWORD in ~/monarch-stack/.env", None, None)
    try:
        import psycopg2
    except ImportError:
        return (MemoryLayerHealth.UNKNOWN, "psycopg2 unavailable", None, None)
    start = time.monotonic()
    try:
        conn = psycopg2.connect(host=_PG_HOST, port=_PG_PORT, dbname=_PG_DB,
                                user=_PG_USER, password=pw, connect_timeout=3)
        try:
            cur = conn.cursor()
            cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
            row = cur.fetchone()
            activity = None
            cur.execute("SELECT to_regclass('public.vault_note_chunks')")
            if cur.fetchone()[0] is not None:
                cur.execute("SELECT count(*) FROM vault_note_chunks")
                activity = f"{cur.fetchone()[0]:,} chunks"
        finally:
            conn.close()
        ms = int((time.monotonic() - start) * 1000)
        if row is None:
            return (MemoryLayerHealth.DEGRADED,
                    "connected; vector extension NOT installed", activity, ms)
        return (MemoryLayerHealth.OK, f"vector {row[0]}", activity, ms)
    except Exception as exc:
        ms = int((time.monotonic() - start) * 1000)
        first = (str(exc).splitlines() or [""])[0][:60]
        return (MemoryLayerHealth.UNRESPONSIVE, f"{type(exc).__name__}: {first}", None, ms)


def _probe_hermes() -> Tuple[MemoryLayerHealth, str, Optional[str], Optional[int]]:
    """L4 — Hermes gateway /health (bearer). state.db mtime is reported as
    activity, never as a health gate."""
    key = os.environ.get("API_SERVER_KEY") or _read_env_value(_HERMES_ENV, "API_SERVER_KEY")
    url = f"http://{_HERMES_HOST}:{_HERMES_PORT}/health"
    start = time.monotonic()
    healthy = False
    try:
        req = urllib.request.Request(url)
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        with urllib.request.urlopen(req, timeout=3):
            healthy = True
    except Exception:
        healthy = False
    ms = int((time.monotonic() - start) * 1000)

    age = _mtime_age_s(_HERMES_STATE_DB)
    activity = f"state.db {_fmt_age(age)}" if age is not None else "state.db absent"
    if healthy:
        return (MemoryLayerHealth.OK, "/health 200", activity, ms)
    return (MemoryLayerHealth.UNRESPONSIVE, "/health no response", activity, ms)


def _probe_vault() -> Tuple[MemoryLayerHealth, str, Optional[str], Optional[int]]:
    """L6 — vault dir writable + git working tree clean. Last commit = activity."""
    if not os.path.isdir(_VAULT_DIR):
        return (MemoryLayerHealth.UNRESPONSIVE, f"{_VAULT_DIR} missing", None, None)
    if not os.access(_VAULT_DIR, os.W_OK):
        return (MemoryLayerHealth.DEGRADED, "vault not writable", None, None)
    start = time.monotonic()
    try:
        r = subprocess.run(["git", "-C", _VAULT_DIR, "status", "--porcelain"],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        ms = int((time.monotonic() - start) * 1000)
        return (MemoryLayerHealth.DEGRADED, "git status failed", None, ms)
    ms = int((time.monotonic() - start) * 1000)

    activity = None
    try:
        lc = subprocess.run(["git", "-C", _VAULT_DIR, "log", "-1", "--format=%ct"],
                            capture_output=True, text=True, timeout=5)
        if lc.returncode == 0 and lc.stdout.strip():
            activity = f"last commit {_fmt_age(int(time.time() - int(lc.stdout.strip())))}"
    except Exception:
        pass

    dirty = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if dirty:
        return (MemoryLayerHealth.DEGRADED,
                f"{len(dirty)} uncommitted change(s)", activity, ms)
    return (MemoryLayerHealth.OK, "clean", activity, ms)


def _scan_skill_drafts() -> Tuple[int, List[str]]:
    """Return (total, stale_names) where stale = age > _STALE_DRAFT_DAYS.
    Age uses SKILL.md mtime when present, else the draft dir mtime."""
    try:
        entries = [e for e in os.listdir(_SKILL_DRAFTS_DIR) if not e.startswith(".")]
    except (FileNotFoundError, PermissionError, OSError):
        return (0, [])
    cutoff = _STALE_DRAFT_DAYS * 86400
    stale: List[str] = []
    for name in entries:
        d = os.path.join(_SKILL_DRAFTS_DIR, name)
        skill_md = os.path.join(d, "SKILL.md")
        age = _mtime_age_s(skill_md if os.path.isfile(skill_md) else d)
        if age is not None and age > cutoff:
            stale.append(name)
    return (len(entries), sorted(stale))


def _scan_gc_proposals() -> Tuple[int, List[str], List[str]]:
    """Return (total, stale_ids, all_ids) for curated-tier GC proposals (§8.8).
    Stale = a proposal unreviewed > _STALE_GC_DAYS. all_ids drives the same-cycle
    "new proposal appeared" notification. Mirrors _scan_skill_drafts: reads the
    filesystem directly, no daemon dependency."""
    try:
        entries = [e for e in os.listdir(_GC_PROPOSALS_DIR) if e.endswith(".json")]
    except (FileNotFoundError, PermissionError, OSError):
        return (0, [], [])
    cutoff = _STALE_GC_DAYS * 86400
    stale: List[str] = []
    for name in entries:
        age = _mtime_age_s(os.path.join(_GC_PROPOSALS_DIR, name))
        if age is not None and age > cutoff:
            stale.append(name[:-5])  # strip .json → proposal id
    ids = [e[:-5] for e in entries]
    return (len(entries), sorted(stale), sorted(ids))


# ─── Listener ─────────────────────────────────────────────────────────────────

class MemoryListener(BaseListener):
    name = "memory"
    interval_sec = 30.0   # finest active cadence (L4); slower layers gated internally

    def __init__(self) -> None:
        super().__init__()
        self._next_due: dict[str, float] = {k: 0.0 for k in _CADENCE}
        self._last_health: dict[str, MemoryLayerHealth] = {}
        self._last_stale: set[str] = set()
        self._last_gc_stale: set[str] = set()
        # None until first sweep: seed silently so a daemon restart with a standing
        # backlog doesn't re-fire "new proposal" pings for already-known proposals.
        self._last_gc_ids: set[str] | None = None

    def poll(self) -> None:
        now = datetime.now(timezone.utc)
        mono = time.monotonic()
        store = StateStore.get()
        snap = store.snapshot()
        prev = snap.memory.layers
        comp = {c.name: c for c in snap.health.components}

        layers: dict[str, MemoryLayer] = {}
        for meta in MONARCH_MEMORY_LAYERS:
            lid = meta["layer"]
            layer = MemoryLayer(
                layer=lid, name=meta["name"], role=meta["role"], mode=meta["mode"],
                source_component=meta.get("component"),
            )
            # Carry forward last-known dynamic fields; probes/refresh overwrite.
            base = prev.get(lid)
            if base is not None:
                layer.health = base.health
                layer.health_signal = base.health_signal
                layer.activity_signal = base.activity_signal
                layer.anomaly = base.anomaly
                layer.last_check = base.last_check
                layer.last_seen_healthy = base.last_seen_healthy
                layer.response_ms = base.response_ms

            mode = meta["mode"]
            if mode == "placeholder":
                layer.health = MemoryLayerHealth.NOT_CONFIGURED
                layer.health_signal = "not built (P1.5-6)"
                layer.last_check = now
            elif mode == "state":
                self._refresh_from_component(layer, comp.get(meta["component"]), now)
            elif mode == "probe":
                if mono >= self._next_due.get(lid, 0.0):
                    self._run_probe(layer, lid, now)
                    self._next_due[lid] = mono + _CADENCE[lid]

            layers[lid] = layer

        total, stale = _scan_skill_drafts()
        gc_total, gc_stale, gc_ids = _scan_gc_proposals()

        def update(model):
            model.memory.layers = layers
            model.memory.last_sweep = now
            model.memory.skill_drafts_total = total
            model.memory.skill_drafts_stale = stale
            model.memory.gc_proposals_total = gc_total
            model.memory.gc_proposals_stale = gc_stale

        store.apply(update)
        self._emit_transitions(layers, stale, gc_stale, gc_ids)

    def _run_probe(self, layer: MemoryLayer, lid: str, now: datetime) -> None:
        if lid == "L3":
            h, sig, act, ms = _probe_pgvector()
        elif lid == "L4":
            h, sig, act, ms = _probe_hermes()
        elif lid == "L6":
            h, sig, act, ms = _probe_vault()
        else:
            return
        layer.health = h
        layer.health_signal = sig
        if act is not None:
            layer.activity_signal = act
        layer.response_ms = ms
        layer.last_check = now
        if h == MemoryLayerHealth.OK:
            layer.last_seen_healthy = now

    def _refresh_from_component(self, layer: MemoryLayer, comp, now: datetime) -> None:
        layer.last_check = now
        if comp is None:
            layer.health = MemoryLayerHealth.UNKNOWN
            layer.health_signal = f"component {layer.source_component} not registered"
            return
        layer.health = _COMPONENT_HEALTH_MAP.get(comp.status.value, MemoryLayerHealth.UNKNOWN)
        layer.health_signal = comp.detail or comp.status.value
        layer.response_ms = comp.response_ms
        if comp.last_seen_healthy is not None:
            layer.last_seen_healthy = comp.last_seen_healthy
        # evercore (es:ok …) / codebase-memory (last_index_activity …) carry rich
        # detail — surface it as the activity signal too.
        if comp.detail:
            layer.activity_signal = comp.detail

    def _emit_transitions(self, layers: dict[str, MemoryLayer], stale: List[str],
                          gc_stale: List[str] | None = None,
                          gc_ids: List[str] | None = None) -> None:
        store = StateStore.get()

        for lid, layer in layers.items():
            prev = self._last_health.get(lid)
            cur = layer.health
            if prev is not None and cur != prev:
                if cur in _UNHEALTHY and prev not in _UNHEALTHY:
                    store.emit(
                        type="memory_layer_unhealthy", severity="warning",
                        detail=f"{lid} {layer.name}: {layer.health_signal}",
                    )
                    logger.warning("[memory] %s %s unhealthy: %s",
                                   lid, layer.name, layer.health_signal)
                elif cur == MemoryLayerHealth.OK and prev in _UNHEALTHY:
                    store.emit(
                        type="memory_layer_recovered", severity="info",
                        detail=f"{lid} {layer.name} recovered",
                    )
                    logger.info("[memory] %s %s recovered", lid, layer.name)
            self._last_health[lid] = cur

        # Stale skill drafts (§11.4) — Tier 2 anomaly, transition-tracked.
        stale_set = set(stale)
        for name in sorted(stale_set - self._last_stale):
            store.emit(
                type="memory_anomaly_detected", severity="warning",
                detail=f"skill draft '{name}' unreviewed >{_STALE_DRAFT_DAYS}d "
                       f"(approve-draft / edit / discard)",
            )
            logger.warning("[memory] stale skill draft: %s", name)
        self._last_stale = stale_set

        # Stale curated-GC proposals (§8.8 / §11.4) — Tier 2 anomaly: a prune/merge
        # proposal piling up unreviewed is the same backlog signal as a stale draft.
        gc_set = set(gc_stale or [])
        for pid in sorted(gc_set - self._last_gc_stale):
            store.emit(
                type="memory_anomaly_detected", severity="warning",
                detail=f"curated-GC proposal '{pid}' unreviewed >{_STALE_GC_DAYS}d "
                       f"(loki-q curated-gc → apply / reject)",
            )
            logger.warning("[memory] stale curated-GC proposal: %s", pid)
        self._last_gc_stale = gc_set

        # New curated-GC proposals appeared this cycle (§8.8) — Tier-2 notify so the
        # operator is told (held to 07:00 by the overnight overlay) instead of having
        # to poll. Seed silently on first sweep so a restart doesn't re-ping a backlog.
        cur_gc = set(gc_ids or [])
        if self._last_gc_ids is None:
            self._last_gc_ids = cur_gc
        else:
            new_gc = cur_gc - self._last_gc_ids
            if new_gc:
                store.emit(
                    type="memory_anomaly_detected", severity="warning",
                    detail=f"{len(new_gc)} new curated-GC proposal(s) pending "
                           f"(total {len(cur_gc)}) — review with `loki-q curated-gc`",
                )
                logger.info("[memory] %d new curated-GC proposal(s): %s",
                            len(new_gc), ", ".join(sorted(new_gc)))
            self._last_gc_ids = cur_gc
