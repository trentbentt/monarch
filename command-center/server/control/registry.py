"""Closed-enum control action registry.

Each action validates its params (no shell, no arbitrary URLs/commands), then
either runs a fixed argv (shell), posts to an allow-listed n8n webhook, or
mutates local state. Dry-run (global or per-call) reports the command without
executing. Every path is audited by the caller.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Callable, List, Optional

import config

_ID_RE = re.compile(r"^[a-z0-9_]+$")
_SHELL_TIMEOUT = 30.0


class ParamError(ValueError):
    pass


# --- param validators --------------------------------------------------------

def _action_id(params: dict) -> str:
    aid = str(params.get("action_id", "")).strip()
    if not aid or len(aid) > 64 or not _ID_RE.match(aid):
        raise ParamError("action_id must match [a-z0-9_]{1,64}")
    return aid


def _ngl(params: dict) -> Optional[int]:
    v = params.get("ngl")
    if v is None or v == "":
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ParamError("ngl must be an integer")
    if not 0 <= n <= 99:
        raise ParamError("ngl out of range (0-99)")
    return n


def _reason(params: dict) -> str:
    r = str(params.get("reason", "")).strip()
    # Strip leading dashes so the reason can never be parsed as a loki-q flag
    # when appended as a trailing argv (e.g. "--force"). argv is a list (no
    # shell), so flag-injection is the only vector left at this boundary.
    r = r.lstrip("-").strip()
    return (r or "operator action (dashboard)")[:200]


# --- action spec -------------------------------------------------------------

@dataclass
class ActionSpec:
    id: str
    label: str
    kind: str            # "shell" | "webhook" | "local"
    danger: str          # "reversible" | "irreversible" | "info"
    needs: List[str]     # param names shown by the UI
    build: Callable      # (cleaned_params) -> argv list | (name, path) | callable


def _argv_authority(sub: str):
    def build(p):
        argv = [config.LOKIQ_BIN, "authority", sub, p["action_id"]]
        if sub == "demote":
            argv.append(p["reason"])
        argv.append("--json")   # structured result — not scraped prose (review A2)
        return argv
    return build


def _argv_t1_offload(p):
    argv = [config.T1_OFFLOAD_BIN]
    if p.get("ngl") is not None:
        argv.append(str(p["ngl"]))
    return argv


_SPECS = {
    "approve": ActionSpec("approve", "Approve action", "shell", "reversible",
                          ["action_id"], _argv_authority("promote")),
    "veto": ActionSpec("veto", "Veto action", "shell", "reversible",
                       ["action_id"], _argv_authority("veto")),
    "demote": ActionSpec("demote", "Demote (revoke trust)", "shell", "reversible",
                         ["action_id", "reason"], _argv_authority("demote")),
    "t1_offload": ActionSpec("t1_offload", "Offload T1 to CPU", "shell", "reversible",
                             ["ngl"], _argv_t1_offload),
    "t1_restore": ActionSpec("t1_restore", "Restore T1 to GPU", "shell", "reversible",
                             [], lambda p: [config.T1_RESTORE_BIN]),
    "workflow_trigger": ActionSpec("workflow_trigger", "Trigger workflow", "webhook",
                                   "irreversible", ["workflow"], None),
    "event_ack": ActionSpec("event_ack", "Acknowledge event", "local", "info",
                            ["event_id"], None),
}


def _clean(name: str, params: dict) -> dict:
    """Per-action validation -> cleaned params (raises ParamError)."""
    if name in ("approve", "veto"):
        return {"action_id": _action_id(params)}
    if name == "demote":
        return {"action_id": _action_id(params), "reason": _reason(params)}
    if name == "t1_offload":
        return {"ngl": _ngl(params)}
    if name == "t1_restore":
        return {}
    if name == "workflow_trigger":
        wf = str(params.get("workflow", "")).strip()
        if wf not in config.WORKFLOWS:
            raise ParamError(f"unknown workflow (allow-listed: {sorted(config.WORKFLOWS)})")
        return {"workflow": wf}
    if name == "event_ack":
        eid = str(params.get("event_id", "")).strip()
        if not eid or len(eid) > 128:
            raise ParamError("event_id required")
        return {"event_id": eid}
    raise KeyError(name)


def list_actions() -> list:
    out = []
    for s in _SPECS.values():
        item = {"id": s.id, "label": s.label, "kind": s.kind, "danger": s.danger, "needs": s.needs}
        if s.id == "workflow_trigger":
            item["workflows"] = sorted(config.WORKFLOWS)
        out.append(item)
    return out


def has(name: str) -> bool:
    return name in _SPECS


async def _run_shell(argv: List[str]) -> dict:
    def _call():
        return subprocess.run(argv, capture_output=True, text=True, timeout=_SHELL_TIMEOUT)
    try:
        proc = await asyncio.to_thread(_call)
    except FileNotFoundError:
        return {"ok": False, "result": "error", "detail": f"not found: {argv[0]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": "error", "detail": "timeout"}
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    # If the tool emitted a --json result object (authority actions do), trust its
    # structured verdict instead of inferring success from the exit code + prose —
    # a CLI wording change can no longer read as a failure (review A2). Falls back
    # to returncode for tools that don't speak JSON (t1_offload/restore).
    if out:
        try:
            parsed = json.loads(out.splitlines()[-1])
        except (ValueError, IndexError):
            parsed = None
        if isinstance(parsed, dict) and "ok" in parsed:
            return {
                "ok": bool(parsed["ok"]),
                "result": parsed.get("result") or ("ok" if parsed["ok"] else "error"),
                "returncode": proc.returncode,
                "detail": str(parsed.get("detail", ""))[-500:],
            }
    return {
        "ok": proc.returncode == 0,
        "result": "ok" if proc.returncode == 0 else "error",
        "returncode": proc.returncode,
        "detail": out[-500:] or err[-500:],
    }


async def _run_webhook(name: str) -> dict:
    import httpx
    path = config.WORKFLOWS[name]
    url = f"{config.N8N_URL.rstrip('/')}/{str(path).lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url)
        return {"ok": r.is_success, "result": "ok" if r.is_success else "error",
                "returncode": r.status_code, "detail": f"n8n {r.status_code}"}
    except Exception as e:
        return {"ok": False, "result": "error", "detail": str(e)[:200]}


def _run_local(name: str, cleaned: dict) -> dict:
    if name == "event_ack":
        from control import acks
        total = acks.ack(cleaned["event_id"])
        return {"ok": True, "result": "ok", "detail": f"acked ({total} total)"}
    return {"ok": False, "result": "error", "detail": "no local handler"}


async def execute(name: str, params: dict, dry_run: bool) -> dict:
    """Validate + (dry-run or execute). Returns a result dict; does NOT audit
    (the caller audits, so denied/validation paths are logged too)."""
    spec = _SPECS[name]
    cleaned = _clean(name, params)
    effective_dry = dry_run or config.CONTROL_DRY_RUN

    if spec.kind == "shell":
        argv = spec.build(cleaned)
        if effective_dry:
            return {"ok": True, "result": "dry_run", "dry_run": True,
                    "would_run": argv, "cleaned": cleaned}
        res = await _run_shell(argv)
    elif spec.kind == "webhook":
        if effective_dry:
            return {"ok": True, "result": "dry_run", "dry_run": True,
                    "would_run": f"POST n8n:{config.WORKFLOWS[cleaned['workflow']]}",
                    "cleaned": cleaned}
        res = await _run_webhook(cleaned["workflow"])
    else:  # local
        if effective_dry:
            return {"ok": True, "result": "dry_run", "dry_run": True,
                    "would_run": f"local:{name}", "cleaned": cleaned}
        res = _run_local(name, cleaned)

    res["cleaned"] = cleaned
    return res
