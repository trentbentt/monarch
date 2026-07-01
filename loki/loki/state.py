"""
Loki State Store v0.2

Architecture change from v0.1: no shared RLock contention.

Pattern:
  - Reads:  acquire lock briefly, deep-copy the model, release, return copy.
  - Writes: pushed as update functions onto a queue. Single writer thread.
  - Events: separate thread-safe ring buffer (collections.deque).
  - Persistence: snapshot pattern. Lock held only for the deep-copy.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Optional

from .schema import (
    ComponentHealth,
    Event,
    Health,
    HealthStatus,
    MONARCH_HEALTH_COMPONENTS,
    MONARCH_TIERS,
    Operator,
    QUOTA_ROLE_KEYS,
    ROLE_MODELS,
    Quotas,
    Resources,
    Schedule,
    SystemModel,
    Tier,
    TierRuntime,
    TierState,
    Workloads,
)

logger = logging.getLogger(__name__)

STATE_PATH = Path(os.environ.get(
    "LOKI_STATE_PATH",
    Path.home() / ".local/state/loki/state.json"
))

_EVENT_BUFFER_MAX = 2000
_WRITE_QUEUE_MAX = 1000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


UpdateFn = Callable[[SystemModel], None]


class StateStore:
    _instance: Optional["StateStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._model_lock = threading.Lock()
        self._model = self._build_initial_model()

        self._write_queue: "queue.Queue[Optional[UpdateFn]]" = queue.Queue(
            maxsize=_WRITE_QUEUE_MAX
        )
        self._writer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._events_lock = threading.Lock()
        self._events: Deque[Event] = deque(maxlen=_EVENT_BUFFER_MAX)

    @classmethod
    def get(cls) -> "StateStore":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        if self._writer_thread is not None and self._writer_thread.is_alive():
            return
        self._stop_event.clear()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="state-writer",
            daemon=True,
        )
        self._writer_thread.start()
        logger.info("[state] writer thread started")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        try:
            self._write_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=timeout)
        logger.info("[state] writer thread stopped")

    def snapshot(self) -> SystemModel:
        with self._model_lock:
            return self._model.model_copy(deep=True)

    def apply(self, fn: UpdateFn, timeout: float = 1.0) -> bool:
        try:
            self._write_queue.put(fn, timeout=timeout)
            return True
        except queue.Full:
            logger.error("[state] write queue full")
            return False

    def emit(
        self,
        type: str,
        severity: str = "info",
        tier: Optional[str] = None,
        workload_id: Optional[str] = None,
        detail: Optional[str] = None,
        **data: Any,
    ) -> None:
        event = Event(
            event_id=str(uuid.uuid4())[:8],
            timestamp=_utcnow(),
            type=type,
            severity=severity,
            tier=tier,
            workload_id=workload_id,
            detail=detail,
            data=data,
        )
        with self._events_lock:
            self._events.append(event)

    def events_snapshot(self) -> list[Event]:
        with self._events_lock:
            return list(self._events)

    def save_to_disk(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

        model_copy = self.snapshot()
        events = self.events_snapshot()
        model_copy.events.log = events

        payload = model_copy.model_dump(mode="json")

        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        tmp.replace(STATE_PATH)

    @classmethod
    def load_from_disk(cls) -> Optional[SystemModel]:
        if not STATE_PATH.exists():
            return None
        try:
            data = json.loads(STATE_PATH.read_text())
            model = SystemModel.model_validate(data)
            # ── Orphan-key prune (D1) ─────────────────────────────────────
            # quotas.quotas is Dict[str,CloudQuota] — Pydantic extra="ignore"
            # does not prune dict-value keys. Prune any key outside the
            # canonical set so runtime always matches _build_initial_model().
            # schema_version is a label field only (D4); no transforms run.
            # P2-2 (2026-06-10): canonical set derives from schema.QUOTA_ROLE_KEYS
            # (role keys, single source). The legacy provider-named keys
            # (claude_pro_1/_2, deepseek_v4_flash, kimi_k2_6, anthropic_api_direct)
            # prune as orphans on first load and the role rows hydrate at
            # cold-start defaults — N=0 per strict cold-start.
            canonical_quota_keys = set(QUOTA_ROLE_KEYS)
            orphans = set(model.quotas.quotas.keys()) - canonical_quota_keys
            if orphans:
                logger.info("load_from_disk: pruning orphan quota keys: %s", sorted(orphans))
                for k in orphans:
                    del model.quotas.quotas[k]
            # Hydrate any canonical keys missing from state.json (e.g. after
            # a provider rename — deepseek_v3 → deepseek_v4_flash). Uses
            # _build_initial_model() defaults so hydrated rows match cold-start.
            missing = canonical_quota_keys - set(model.quotas.quotas.keys())
            if missing:
                fresh = cls._build_initial_model()
                for k in missing:
                    logger.info("load_from_disk: hydrating missing quota key: %s", k)
                    model.quotas.quotas[k] = fresh.quotas.quotas[k]

            # Health-component reconciliation (same philosophy as quota hydration).
            # state.json persists the last component list; when a new service is
            # added to MONARCH_HEALTH_COMPONENTS (e.g. evercore, rerank-bge), hydrate
            # it here so a daemon restart picks it up without discarding state.json.
            # Preserve existing components' runtime state, add missing in canonical
            # order, prune any no longer in the canonical set, and keep ports in sync.
            canonical = {c["name"]: c for c in MONARCH_HEALTH_COMPONENTS}
            existing = {c.name: c for c in model.health.components}
            orphans = set(existing) - set(canonical)
            if orphans:
                logger.info("load_from_disk: pruning orphan health components: %s", sorted(orphans))
            reconciled = []
            for name, c in canonical.items():
                if name in existing:
                    comp = existing[name]
                    comp.port = c["port"]
                    reconciled.append(comp)
                else:
                    logger.info("load_from_disk: hydrating missing health component: %s", name)
                    reconciled.append(ComponentHealth(name=name, port=c["port"],
                                                       status=HealthStatus.UNKNOWN))
            model.health.components = reconciled
            # ── End orphan-key prune ──────────────────────────────────────
            return model
        except Exception as e:
            logger.error("Failed to parse state file: %s", e)
            return None

    def _writer_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                fn = self._write_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if fn is None:
                break

            start = _utcnow()
            try:
                with self._model_lock:
                    fn(self._model)
                    self._model.last_updated = _utcnow()
            except Exception as exc:
                logger.error("[state] update fn raised %s: %s",
                             type(exc).__name__, exc, exc_info=True)
            finally:
                elapsed = (_utcnow() - start).total_seconds()
                if elapsed > 0.5:
                    logger.warning("[state] slow update fn: %.2fs", elapsed)

    @staticmethod
    def _build_initial_model() -> SystemModel:
        tiers = {
            tid: Tier(
                config=cfg,
                runtime=TierRuntime(
                    state=TierState.OFFLINE if not cfg.enabled else TierState.STOPPED
                ),
            )
            for tid, cfg in MONARCH_TIERS.items()
        }

        health_components = [
            ComponentHealth(
                name=c["name"],
                port=c["port"],
                status=HealthStatus.UNKNOWN,
            )
            for c in MONARCH_HEALTH_COMPONENTS
        ]

        from .schema import CloudQuota, QuotaStatus
        # P2-2 (2026-06-10): rows derive from schema.ROLE_MODELS — provider
        # model-name strings and budgets live in exactly one place. Subscription
        # roles (api_metered=False) track used_pct; API roles track used_usd.
        quotas_dict = {
            role: CloudQuota(
                name=role,
                provider=spec["provider"],
                period=spec["period"],
                budget_usd=spec["budget_usd"],
                used_usd=0.0 if spec["api_metered"] else None,
                status=QuotaStatus.OK,
            )
            for role, spec in ROLE_MODELS.items()
            if spec.get("quota_row", True)
        }

        return SystemModel(
            tiers=tiers,
            workloads=Workloads(),
            schedule=Schedule(),
            quotas=Quotas(quotas=quotas_dict),
            resources=Resources(),
            operator=Operator(),
            health=Health(components=health_components),
            daemon_pid=os.getpid(),
        )
