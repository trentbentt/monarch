"""Workflows deep-dive provider.

The dashboard's Workflows card shows only n8n health, but n8n was ruled out as
the orchestration path — the workflows the operator actually built are the
**news-pipeline** and the **evidence layer** (run on-demand via Cowork, not as a
daemon). This provider represents them for real.

Structural truth (manifest) is a hand-authored registry: what each workflow is,
its repo, the stage chain, and the doctrine behind it — this is what the scoped
supervisor needs to cite real source. Live truth (detail) is intentionally
decoupled from the projects' Postgres schemas: it reads each repo's optional
``status.json`` (a project drops one after a run) plus filesystem freshness and
n8n health from Loki state. No DB coupling; a live Postgres reader is a later
spec, gated on the pipelines running on a cadence.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .base import DeepDiveProvider, _worst

_HOME = Path.home()


def _proj(name: str) -> Path:
    """Resolve a project dir, env-overridable so tests can point elsewhere."""
    return Path(os.environ.get(f"CC_PROJ_{name.upper().replace('-', '_')}",
                               str(_HOME / "projects" / name)))


# The registry. Order is the operator's mental order: ingest → verify → ship.
_WORKFLOWS = [
    {
        "name": "news-pipeline",
        "what": "Ingests RSS/NewsAPI/GitHub feeds and routes every claim through "
                "a deterministic verification gate before any LLM writes prose.",
        "dir": "news-pipeline",
        "doctrine": ["news_pipeline_architecture_v18.md", "CONSTITUTION.md"],
        "stages": [
            {"key": "ingest", "label": "Ingest", "what": "Pull feeds → raw claims"},
            {"key": "verify", "label": "Verify", "what": "Deterministic gate per claim"},
            {"key": "fuse", "label": "Fuse", "what": "Corroborate across sources"},
            {"key": "adjudicate", "label": "Adjudicate", "what": "Authority + importance"},
            {"key": "render", "label": "Render", "what": "LLM writes the brief"},
        ],
    },
    {
        "name": "evidence-layer",
        "what": "The deterministic accuracy substrate: a grounded ledger that "
                "refuses ungrounded claims. The LLM writes; it never decides truth.",
        "dir": "evidence-layer",
        "doctrine": ["evidence-layer/ACCURACY_SPEC.md", "evidence-layer/BIBLE_v5.md"],
        "stages": [
            {"key": "canonicalize", "label": "Canonicalize", "what": "Normalize signals"},
            {"key": "corroborate", "label": "Corroborate", "what": "Fuse evidence families"},
            {"key": "ledger", "label": "Ledger", "what": "Grounded ev_* rows"},
            {"key": "adjudicate", "label": "Adjudicate", "what": "Refuse ungrounded"},
        ],
    },
    {
        "name": "news-pipeline-evidence-ship",
        "what": "The project archive and design center of mass — runbook, "
                "accuracy spec, and the working evidence-layer package.",
        "dir": "news-pipeline-evidence-ship",
        "doctrine": ["ROADMAP.md", "evidence-layer/HANDOFF.md"],
        "stages": [],
    },
]

# A status.json may be absent; when present we read these keys leniently.
_STATUS_FILE = "status.json"
_FRESH_OK_SEC = 24 * 3600      # a run within a day reads as fresh
_FRESH_WARN_SEC = 7 * 24 * 3600


def _read_status(repo: Path) -> dict | None:
    f = repo / _STATUS_FILE
    try:
        if f.is_file():
            return json.loads(f.read_text())
    except (OSError, ValueError):
        return {"_error": "status.json present but unreadable"}
    return None


def _freshness(repo: Path, status: dict | None) -> tuple[str, str | None]:
    """(status_level, iso_or_none) from the status manifest's timestamp if any,
    else the repo's most recent mtime as a coarse 'last touched' signal."""
    ts = None
    if status:
        ts = status.get("last_run") or status.get("updated_at") or status.get("ts")
    epoch = None
    if isinstance(ts, (int, float)):
        epoch = float(ts)
    elif isinstance(ts, str):
        try:
            from datetime import datetime

            epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            epoch = None
    if epoch is None:
        try:
            epoch = repo.stat().st_mtime if repo.exists() else None
        except OSError:
            epoch = None
    if epoch is None:
        return "unknown", None
    age = time.time() - epoch
    level = "ok" if age < _FRESH_OK_SEC else "warn" if age < _FRESH_WARN_SEC else "crit"
    from datetime import datetime, timezone

    return level, datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _n8n(state: dict) -> dict | None:
    for c in (state or {}).get("health", {}).get("components", []) or []:
        if c.get("name") == "n8n":
            return c
    return None


class WorkflowsProvider(DeepDiveProvider):
    key = "workflows"
    label = "Workflows"

    def manifest(self) -> dict:
        return {
            "lede": "The operator's deterministic news pipeline and its evidence "
                    "layer — claims are verified before any model writes prose. "
                    "Run on-demand, wrong at a known, low, auditable rate.",
            "items": [
                {
                    "name": w["name"],
                    "what": w["what"],
                    "repo": str(_proj(w["dir"])),
                    "doctrine": w["doctrine"],
                    "stages": w["stages"],
                }
                for w in _WORKFLOWS
            ],
            "doctrine": ["final_master_summary.md §E (workflows)",
                         "news_pipeline_architecture_v18.md"],
            "suggestions": [
                "How does the news-pipeline verify a claim before the LLM writes?",
                "What does the evidence layer's ledger refuse, and where in code?",
                "Which workflow ran most recently, and is anything stale?",
                "Walk me through the pipeline stages end to end.",
            ],
        }

    def detail(self, state: dict) -> dict:
        items: dict = {}
        notes: list = []
        levels: list = []
        for w in _WORKFLOWS:
            repo = _proj(w["dir"])
            present = repo.exists()
            status_json = _read_status(repo) if present else None
            if status_json and status_json.get("_error"):
                notes.append(f"{w['name']}: {status_json['_error']}")
                status_json = None
            level, iso = _freshness(repo, status_json) if present else ("unknown", None)
            if not present:
                notes.append(f"{w['name']}: repo not found at {repo}")
            items[w["name"]] = {
                "status": level,
                "last_run": iso,
                "present": present,
                "reporting": status_json is not None,
                # Surface a couple of common manifest keys if the project drops them.
                "summary": (status_json or {}).get("summary"),
                "metrics": (status_json or {}).get("metrics"),
            }
            levels.append(level)

        n8n = _n8n(state)
        n8n_level = _interp_n8n(n8n)

        facts = [
            {"label": "Workflows", "value": str(len(_WORKFLOWS)),
             "status": "ok", "sub": "registered"},
            {"label": "Reporting", "value": str(sum(1 for i in items.values() if i["reporting"])),
             "status": _worst(levels), "sub": f"of {len(_WORKFLOWS)}"},
            {"label": "n8n engine", "value": _N8N_WORD.get(n8n_level, "Unknown"),
             "status": n8n_level, "sub": "orchestration (legacy)"},
        ]
        payload = {"facts": facts, "items": items, "notes": notes}

        # Additive live layer (spec 4): when a workflows DB is configured AND
        # reachable, enrich with run history + grounding. Dormant by default —
        # absent/unreachable DB leaves the payload exactly as above.
        self._enrich_live(payload, items)
        return payload

    @staticmethod
    def _enrich_live(payload: dict, items: dict) -> None:
        """Fold the read-only Postgres rollups into the detail payload, in place.
        Never raises: pg_reader returns notes, and the import is guarded."""
        try:
            import pg_reader
        except Exception:  # noqa: BLE001 — reader absent → stay dormant
            return
        if not pg_reader.available().get("ok"):
            return

        runs = pg_reader.news_runs(14)
        grounding = pg_reader.ledger_summary(30)
        sources = pg_reader.source_authority(8)
        for block in (runs, grounding, sources):
            if block.get("error"):
                payload["notes"].append(f"live: {block['error']}")

        latest = (runs.get("runs") or [None])[0]
        if latest:
            lvl = {"complete": "ok", "partial": "warn", "running": "warn",
                   "failed": "crit"}.get((latest.get("status") or "").lower(), "unknown")
            payload["facts"].append(
                {"label": "Last run", "value": latest.get("run_date", "—"),
                 "status": lvl, "sub": latest.get("status", "")}
            )
            np = items.get("news-pipeline")
            if np and latest.get("completed_at"):
                np["last_run"] = latest["completed_at"]
        if grounding.get("total"):
            rate = grounding.get("corrob_rate")
            payload["facts"].append(
                {"label": "Grounding", "value": f"{int(round(rate * 100))}%" if rate is not None else "—",
                 "status": "ok", "sub": f"{grounding['total']} ledger rows"}
            )
        if sources.get("sources"):
            payload["facts"].append(
                {"label": "Sources", "value": str(len(sources["sources"])),
                 "status": "ok", "sub": "tracked"}
            )

        payload["runs"] = runs.get("runs", [])
        payload["grounding"] = {
            "verdicts": grounding.get("verdicts", {}),
            "corrob_rate": grounding.get("corrob_rate"),
            "total": grounding.get("total", 0),
            "briefs": grounding.get("briefs", 0),
            "sources": sources.get("sources", []),
        }

    def status(self, state: dict, detail: dict | None = None) -> str:
        d = detail if detail is not None else self.detail(state)
        # Workflow freshness drives the light; n8n being down is informational
        # only (it isn't the chosen orchestration path), so it can't crit the dome.
        levels = [i.get("status") for i in d.get("items", {}).values()]
        return _worst(levels)


_N8N_WORD = {"ok": "Online", "warn": "Degraded", "crit": "Down", "unknown": "Unknown"}


def _interp_n8n(c: dict | None) -> str:
    if not c:
        return "unknown"
    s = (c.get("status") or "").lower()
    if s in ("ok", "healthy", "up", "online"):
        return "ok"
    if s in ("warn", "degraded"):
        return "warn"
    if s in ("crit", "down", "dead", "error"):
        return "crit"
    return "unknown"
