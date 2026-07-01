"""
Quota Listener v0.2

LiteLLM spend & token tracking. Polls the litellm_logs DB every 60s and
attributes per-model spend/tokens to the cloud quota rows Loki budgets.

Spec: master_summary §12.4 ("quota.py — LiteLLM spend & token tracking";
LiteLLM logging Path A).

── Phase A (current) ─────────────────────────────────────────────────────────
Code-only. The live DB is NOT yet wired (Path A deferred — see the private
monarch-stack design notes for the LiteLLM logging target). When
LITELLM_DB_URL is unset, the DB is unreachable, or the spend table is absent,
this listener runs DORMANT: it logs the condition once and returns, leaving
quota rows at their cold-start values. Mirrors cmd_quotas' "no quota data yet".

── Reality note (2026-05-29) ──────────────────────────────────────────────────
Cloud fallback lanes are DISABLED in ~/litellm/config.yaml. Even once Path A is
wired, spend_logs will hold only local zero-cost rows until cloud routing is
restored — so cloud quota rows stay at $0 / last_call=never by design.

── Schema self-resolution ─────────────────────────────────────────────────────
The spend-log table name + timestamp column differ between LiteLLM versions
(LiteLLM_SpendLogs.startTime vs the doctrine's spend_logs.start_time). Rather
than hardcode, this listener resolves them against the live DB at first
successful connect via to_regclass + information_schema. 429s are NOT in
spend_logs, so walls_in_window is left untouched (0) in Phase A.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .base import BaseListener
from ..schema import ROLE_MODELS, QuotaStatus
from ..state import StateStore

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2 import sql as _sql
except Exception:  # driver absent — listener stays dormant
    psycopg2 = None
    _sql = None

_DB_URL_ENV = "LITELLM_DB_URL"
_CONNECT_TIMEOUT = 3
_SPEND_BURST_USD_PER_MIN = 1.0

# spend_logs.model value → CloudQuota role key, DERIVED from schema.ROLE_MODELS
# (P2-2 role-key indirection — model-name strings live in schema.py only).
# Local models (qwen3.6-*, phi4-mini, …) are $0 and intentionally unmapped.
# pro_* and frontier_direct carry empty litellm_models tuples (Pro descoped;
# frontier_direct is a forward-compat hook) — they stay dormant by design.
_MODEL_TO_QUOTA: Dict[str, str] = {
    model: role
    for role, spec in ROLE_MODELS.items()
    for model in spec["litellm_models"]
}

# Candidate spend-log tables (LiteLLM default first; doctrine name fallback) and
# timestamp columns. Resolved once against the live DB. Unquoted names; quoting
# is handled per-use (to_regclass arg, then psycopg2.sql.Identifier).
_TABLE_CANDIDATES = ["LiteLLM_SpendLogs", "spend_logs"]
_TS_CANDIDATES = ["startTime", "start_time", "starttime"]


def _aware(ts: Optional[datetime]) -> Optional[datetime]:
    """Coerce a DB timestamp to UTC-aware. A `timestamp without time zone` column
    yields a NAIVE datetime from psycopg2; stored unchanged into last_call_ts it
    later crashes `loki-q quotas` on `datetime.now(utc) - last_call_ts`
    (aware − naive → TypeError). LiteLLM writes startTime in UTC, so anchoring a
    naive value to UTC is correct."""
    if ts is not None and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


class QuotaListener(BaseListener):
    name = "quota"
    interval_sec = 60.0

    def __init__(self) -> None:
        super().__init__()
        self._dormant_logged = False
        self._table: Optional[str] = None
        self._ts_col: Optional[str] = None
        self._last_status: Dict[str, QuotaStatus] = {}
        self._last_spend: Dict[str, Tuple[float, float]] = {}  # key -> (used_usd, monotonic)
        self._conn = None   # persistent DB connection, reused across polls

    def _log_dormant(self, msg: str) -> None:
        if not self._dormant_logged:
            logger.info("[quota] dormant: %s", msg)
            self._dormant_logged = True

    def _get_conn(self, db_url: str):
        """Return a live psycopg2 connection, reusing the one held across polls.
        Reconnects only when there is no connection or the server dropped it
        (conn.closed != 0). autocommit=True keeps this read-only poller from
        sitting idle-in-transaction between the 60s ticks."""
        if self._conn is not None and getattr(self._conn, "closed", 1) == 0:
            return self._conn
        conn = psycopg2.connect(db_url, connect_timeout=_CONNECT_TIMEOUT)
        conn.autocommit = True
        self._conn = conn
        return self._conn

    def _reset_conn(self) -> None:
        """Drop the held connection (close best-effort) so the next poll
        reconnects — called after a connect/query failure poisons it."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def poll(self) -> None:
        db_url = os.environ.get(_DB_URL_ENV)
        if not db_url:
            self._log_dormant(f"{_DB_URL_ENV} unset — Path A not wired (Phase B deferred)")
            return
        if psycopg2 is None:
            self._log_dormant("psycopg2 not available in venv")
            return

        try:
            conn = self._get_conn(db_url)
        except Exception as exc:
            self._reset_conn()
            self._log_dormant(f"connect failed: {type(exc).__name__}")
            return

        try:
            rows = self._query(conn)
        except Exception as exc:
            # The connection may be poisoned (broken socket, aborted txn); drop
            # it so the next poll reconnects instead of reusing a dead handle.
            self._reset_conn()
            self._log_dormant(f"query failed: {type(exc).__name__}: {exc}")
            return

        if rows is None:  # table not found — dormant logged inside _query
            return

        # Live connection + resolved table → no longer dormant.
        self._dormant_logged = False
        self._apply_rows(rows)

    def _resolve_schema(self, cur) -> bool:
        """Resolve the spend-log table + timestamp column against the live DB.
        Cached after first success. Returns False if no candidate table exists."""
        if self._table and self._ts_col:
            return True
        for name in _TABLE_CANDIDATES:
            cur.execute("SELECT to_regclass(%s)", ('"%s"' % name,))
            if cur.fetchone()[0] is not None:
                self._table = name
                break
        if not self._table:
            return False
        # Bind columns to the EXACT relation to_regclass resolved above (same
        # search_path resolution), via its OID — information_schema.columns
        # filtered on table_name alone can pull columns from a same-named table
        # in another schema and bind a ts column the real table lacks, raising
        # every 60s poll and leaving the listener permanently dormant.
        cur.execute(
            "SELECT attname FROM pg_attribute "
            "WHERE attrelid = to_regclass(%s) AND attnum > 0 AND NOT attisdropped",
            ('"%s"' % self._table,),
        )
        cols = {r[0] for r in cur.fetchall()}
        for c in _TS_CANDIDATES:
            if c in cols:
                self._ts_col = c
                break
        return self._ts_col is not None

    def _query(self, conn) -> Optional[List[tuple]]:
        """Per-model CUMULATIVE spend (prepaid-balance depletion) plus today's
        spend/tokens and the most-recent call ts. None if no spend table.

        §9.5.4 models cloud quotas as a manually-loaded PREPAID BALANCE with no
        periodic reset — Loki treats remaining balance as a hard floor. So the
        budget comparison is cumulative spend vs the loaded balance (budget_usd),
        NOT a calendar day/week/month slice. The *_today fields still need today's
        slice, aggregated in the same pass via FILTER. (Anchoring the cumulative
        sum at the balance-reload instant is future work for when period_start is
        populated on reload; in Phase A the spend log is per-balance-era.)"""
        with conn.cursor() as cur:
            if not self._resolve_schema(cur):
                self._log_dormant("no spend-log table found (LiteLLM_SpendLogs / spend_logs)")
                return None
            q = _sql.SQL(
                "SELECT model, "
                "COALESCE(SUM(spend),0)::float8, "
                "COALESCE(SUM(spend) FILTER (WHERE {ts} >= date_trunc('day', now())),0)::float8, "
                "COALESCE(SUM(prompt_tokens) FILTER (WHERE {ts} >= date_trunc('day', now())),0)::bigint, "
                "COALESCE(SUM(completion_tokens) FILTER (WHERE {ts} >= date_trunc('day', now())),0)::bigint, "
                "MAX({ts}) "
                "FROM {tbl} "
                "GROUP BY model"
            ).format(ts=_sql.Identifier(self._ts_col), tbl=_sql.Identifier(self._table))
            cur.execute(q)
            return cur.fetchall()

    def _apply_rows(self, rows: List[tuple]) -> None:
        now = datetime.now(timezone.utc)
        mono = time.monotonic()

        # Aggregate per quota key (several model strings may map to one key).
        agg: Dict[str, dict] = {}
        for model, cum_spend, today_spend, ptok, ctok, last_ts in rows:
            key = _MODEL_TO_QUOTA.get(model)
            if key is None:
                continue
            last_ts = _aware(last_ts)
            a = agg.setdefault(key, {"cum": 0.0, "today": 0.0,
                                     "in": 0, "out": 0, "last": None})
            a["cum"] += float(cum_spend or 0.0)
            a["today"] += float(today_spend or 0.0)
            a["in"] += int(ptok or 0)
            a["out"] += int(ctok or 0)
            if last_ts is not None and (a["last"] is None or last_ts > a["last"]):
                a["last"] = last_ts

        if not agg:
            return

        store = StateStore.get()
        snap = store.snapshot()

        payloads: Dict[str, dict] = {}
        events: List[Tuple[str, str, str]] = []  # (type, severity, detail)

        for key, a in agg.items():
            q = snap.quotas.quotas.get(key)
            budget = q.budget_usd if q else None
            warn = q.threshold_warning_pct if q else 80.0
            # §9.5.4: prepaid balance, hard floor — compare CUMULATIVE spend
            # against the loaded balance (budget_usd), not a daily/period slice.
            # today's numbers feed the *_today fields below.
            used = a["cum"]

            # budget_usd == 0.0 is a HARD block, not "untracked" — only a None
            # budget is untracked. A $0 lane reports WALLED immediately (even
            # with zero spend): nothing remains on the floor, so the lane is
            # not routable — agents reading quotas must not see OK here
            # (operator-decided 2026-06-10; §9.5.4 hard floor).
            if budget is None:
                pct = None
            elif budget <= 0:
                pct = 100.0
            else:
                pct = used / budget * 100.0

            if pct is not None and pct >= 100.0:
                status = QuotaStatus.WALLED
            elif pct is not None and pct >= warn:
                status = QuotaStatus.APPROACHING_WALL
            else:
                status = QuotaStatus.OK

            # Status-transition events only (never per-poll spam).
            prev = self._last_status.get(key, QuotaStatus.OK)
            if status != prev:
                if status == QuotaStatus.WALLED:
                    events.append(("quota_exceeded", "critical",
                                   f"{key} budget exceeded: ${used:.2f}/${budget:.2f}"))
                elif status == QuotaStatus.APPROACHING_WALL:
                    events.append(("quota_approaching", "warning",
                                   f"{key} approaching budget: ${used:.2f}/${budget:.2f} ({pct:.0f}%)"))
            self._last_status[key] = status

            # Spend-burst: inter-poll burn rate; emit if > $1/min.
            burn_per_hour: Optional[float] = None
            prev_spend = self._last_spend.get(key)
            if prev_spend is not None:
                pu, pm = prev_spend
                dt_min = (mono - pm) / 60.0
                if dt_min > 0 and used >= pu:
                    rate = (used - pu) / dt_min
                    burn_per_hour = rate * 60.0
                    if rate > _SPEND_BURST_USD_PER_MIN:
                        events.append(("spend_burst", "warning",
                                       f"{key} spend burst: ${rate:.2f}/min"))
            self._last_spend[key] = (used, mono)

            payloads[key] = {
                "used": used, "today": a["today"], "in": a["in"], "out": a["out"],
                "last": a["last"], "status": status, "burn": burn_per_hour,
            }

        def update(model):
            for key, p in payloads.items():
                q = model.quotas.quotas.get(key)
                if q is None:
                    continue
                q.used_usd = p["used"]
                q.spend_today_usd = p["today"]
                q.tokens_in_today = p["in"]
                q.tokens_out_today = p["out"]
                q.last_call_ts = p["last"]
                q.status = p["status"]
                if p["burn"] is not None:
                    q.burn_rate_per_hour = p["burn"]
                q.last_updated = now

        store.apply(update)
        for etype, sev, detail in events:
            store.emit(type=etype, severity=sev, detail=detail)
            logger.info("[quota] %s: %s", etype, detail)
