"""Read-only Postgres reader for the Workflows live data (spec 4).

DORMANT BY DEFAULT. When `CC_WORKFLOWS_DB_URL` (news pipeline) and/or
`CC_EVIDENCE_DB_URL` (evidence layer) are unset, `available()` reports False and
`WorkflowsProvider` behaves exactly as spec 1 (status.json + filesystem
freshness). Set the DSNs — pointing at a dedicated SELECT-only `cc_reader` role —
to light up the run history and grounding panels.

Posture (defense in depth even though every statement is a SELECT):
  • DSNs come from the environment, never hardcoded, never serialized to a client.
  • `cc_reader` is granted SELECT only (a documented one-time migration).
  • Every query is parameterized, column-explicit, LIMIT-capped, ordered by date,
    and runs under a per-session statement_timeout. No operator input touches SQL.
  • Never raises: connection/timeout/SQL errors become {error}/available:False.
"""
from __future__ import annotations

import os
from functools import lru_cache

_STMT_TIMEOUT_MS = 2000
_CONNECT_TIMEOUT_S = 3


def _workflows_dsn() -> str | None:
    return os.environ.get("CC_WORKFLOWS_DB_URL") or None


def _evidence_dsn() -> str | None:
    # Evidence tables may share the news DB; default to the workflows DSN.
    return os.environ.get("CC_EVIDENCE_DB_URL") or _workflows_dsn()


def _connect(dsn: str):
    """Read-only-by-use psycopg2 connection with a hard statement timeout. Lazy
    import so the module loads (and the dashboard runs) without psycopg2."""
    import psycopg2  # lazy: absent → caller degrades
    conn = psycopg2.connect(dsn, connect_timeout=_CONNECT_TIMEOUT_S)
    conn.set_session(readonly=True, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = %s", (_STMT_TIMEOUT_MS,))
    return conn


def available() -> dict:
    """Is any workflows DB configured and reachable? Cached briefly so the
    deep-dive doesn't reconnect on every poll."""
    return _available_cached(_workflows_dsn(), _evidence_dsn())


@lru_cache(maxsize=4)
def _available_cached(wf_dsn: str | None, ev_dsn: str | None) -> dict:
    if not wf_dsn and not ev_dsn:
        return {"ok": False, "detail": "no workflows DB configured (dormant)"}
    for dsn in (wf_dsn, ev_dsn):
        if not dsn:
            continue
        try:
            conn = _connect(dsn)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            finally:
                conn.close()
            return {"ok": True, "detail": "workflows DB reachable"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"workflows DB unreachable: {type(exc).__name__}"}
    return {"ok": False, "detail": "no workflows DB configured (dormant)"}


def news_runs(n: int = 14) -> dict:
    """Recent news-pipeline runs, newest first. {runs:[...], error}."""
    dsn = _workflows_dsn()
    if not dsn:
        return {"runs": [], "error": None}
    n = max(1, min(int(n or 14), 60))
    try:
        conn = _connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_date, status, articles_fetched, articles_used, "
                    "api_calls_made, total_tokens, errors, brief_path, completed_at "
                    "FROM news_pipeline_runs ORDER BY run_date DESC LIMIT %s",
                    (n,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return {"runs": [], "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    runs = [
        {
            "run_date": str(r[0]), "status": r[1],
            "articles_fetched": r[2], "articles_used": r[3],
            "api_calls_made": r[4], "total_tokens": r[5],
            "errors": r[6], "brief_path": r[7],
            "completed_at": str(r[8]) if r[8] else None,
        }
        for r in rows
    ]
    return {"runs": runs, "error": None}


def ledger_summary(days: int = 30) -> dict:
    """Evidence-layer grounding rollup over the recent window: verdict
    distribution, independent-corroboration rate, distinct brief count."""
    dsn = _evidence_dsn()
    if not dsn:
        return {"verdicts": {}, "corrob_rate": None, "total": 0, "briefs": 0, "error": None}
    days = max(1, min(int(days or 30), 365))
    try:
        conn = _connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT verdict, count(*) FROM ev_ledger "
                    "WHERE brief_date >= (CURRENT_DATE - %s::int) GROUP BY verdict",
                    (days,),
                )
                verdicts = {row[0]: int(row[1]) for row in cur.fetchall()}
                cur.execute(
                    "SELECT count(*), "
                    "AVG(CASE WHEN independent_corrob > 0 THEN 1.0 ELSE 0.0 END), "
                    "count(DISTINCT brief_date) "
                    "FROM ev_ledger WHERE brief_date >= (CURRENT_DATE - %s::int)",
                    (days,),
                )
                total, rate, briefs = cur.fetchone()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return {"verdicts": {}, "corrob_rate": None, "total": 0, "briefs": 0,
                "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    return {
        "verdicts": verdicts,
        "corrob_rate": round(float(rate), 3) if rate is not None else None,
        "total": int(total or 0),
        "briefs": int(briefs or 0),
        "error": None,
    }


def source_authority(top: int = 10) -> dict:
    """Top learned sources by authority score. {sources:[...], error}."""
    dsn = _evidence_dsn()
    if not dsn:
        return {"sources": [], "error": None}
    top = max(1, min(int(top or 10), 50))
    try:
        conn = _connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT discovered_via, score, survived, total "
                    "FROM ev_source_authority ORDER BY score DESC LIMIT %s",
                    (top,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return {"sources": [], "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    return {
        "sources": [
            {"discovered_via": r[0], "score": round(float(r[1]), 3),
             "survived": r[2], "total": r[3]}
            for r in rows
        ],
        "error": None,
    }
