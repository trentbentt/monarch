"""Read-only API routes — Phase 1.

Endpoints:
  GET /api/health            backend liveness (not the substrate's)
  GET /api/overview          derived Overview (all 10 domains rolled up)
  GET /api/state             full raw state.json (single-operator; small)
  GET /api/domain/{name}     one raw domain dict
  GET /api/stream            SSE: {overview, state} pushed on every change
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

import docs_router
from control import audit, registry
from control.auth import require_control_token, require_read_token, require_read_token_sse
from derive import derive_overview
from legibility import derive_routing, enrich_pending
from reader import stores

router = APIRouter(prefix="/api")

# Raw top-level domains a client may request individually.
_DOMAINS = {
    "hardware", "tiers", "workloads", "schedule", "quotas", "resources",
    "operator", "events", "health", "memory", "decisions",
}


def _watcher(request: Request):
    return request.app.state.watcher


@router.get("/health")
async def backend_health():
    return {"status": "ok", "service": "command-center"}


@router.get("/overview", dependencies=[Depends(require_read_token)])
async def overview(request: Request):
    state = _watcher(request).current()
    return derive_overview(state).model_dump()


@router.get("/state", dependencies=[Depends(require_read_token)])
async def full_state(request: Request):
    return _watcher(request).current()


@router.get("/domain/{name}", dependencies=[Depends(require_read_token)])
async def domain(name: str, request: Request):
    if name not in _DOMAINS:
        raise HTTPException(status_code=404, detail=f"unknown domain: {name}")
    return {name: _watcher(request).current().get(name)}


@router.get("/deep/{name}", dependencies=[Depends(require_read_token)])
async def deep(name: str, request: Request):
    """Full deep-dive payload for one domain: {key, label, status, manifest,
    detail}. The manifest is structural truth (repos/paths/doctrine/stages); the
    detail is the live slice. 404 if the domain has no provider yet."""
    from deepdive import deep_payload

    # Blocking (sync psycopg2 / subprocess / vault rglob+read_text) → worker
    # thread so a cold DB or large scan can't freeze the loop + every SSE stream.
    payload = await asyncio.to_thread(deep_payload, name, _watcher(request).current())
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no deep-dive for domain: {name}")
    return payload


# --- Phase 2: legibility -----------------------------------------------------

@router.get("/routing", dependencies=[Depends(require_read_token)])
async def routing(request: Request):
    return derive_routing(_watcher(request).current())


@router.get("/pending", dependencies=[Depends(require_read_token)])
async def pending(request: Request):
    return {"pending": enrich_pending(_watcher(request).current())}


@router.get("/memory/queues", dependencies=[Depends(require_read_token)])
async def memory_queues(request: Request):
    return stores.memory_queues()


@router.get("/docs/search", dependencies=[Depends(require_read_token)])
async def docs_search(q: str = "", limit: int = 12):
    # Blocking full-vault rglob + read_text → worker thread (see /deep).
    return await asyncio.to_thread(docs_router.search, q, limit=limit)


# --- Memory deep-dive: L6 vault browser + L3 semantic search -----------------

@router.get("/memory/vault/tree", dependencies=[Depends(require_read_token)])
async def memory_vault_tree():
    """The in-scope vault as a nested tree (relative paths only)."""
    import vault_reader
    return vault_reader.tree()


@router.get("/memory/vault/note", dependencies=[Depends(require_read_token)])
async def memory_vault_note(path: str = ""):
    """One vault note's markdown + heading outline. 404 if out of scope/absent."""
    import vault_reader
    note = vault_reader.read(path)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found or out of scope")
    return note


@router.post("/memory/search", dependencies=[Depends(require_read_token)])
async def memory_search(body: dict = Body(...)):
    """L3 semantic search over the embedded vault (via the Loki retrieval layer).
    Blocking (embed + SQL) → runs in a worker thread. Degrades to a clear note."""
    import retrieval_bridge
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="missing query")
    k = body.get("k", 8)
    result = await asyncio.to_thread(retrieval_bridge.search_vault, query, k)
    result["routing"] = retrieval_bridge.route_layers(query).get("layers", [])
    return result


# --- Codebase deep-dive: L5 structural index ---------------------------------

@router.get("/codebase/projects")
async def codebase_projects():
    """Indexed repos with node/edge/size from the L5 structural index."""
    import codebase_bridge
    return await asyncio.to_thread(codebase_bridge.projects)


@router.get("/codebase/search", dependencies=[Depends(require_read_token)])
async def codebase_search(project: str = "", q: str = "", k: int = 40):
    """Structural code search within one indexed project. Blocking CLI → thread."""
    import codebase_bridge
    if not project or not q:
        raise HTTPException(status_code=400, detail="missing project or q")
    return await asyncio.to_thread(codebase_bridge.search, project, q, k)


# --- Supervisor console (T1 read-and-propose chat) ---------------------------

@router.post("/supervisor/ask", dependencies=[Depends(require_read_token)])
async def supervisor_ask(request: Request, body: dict = Body(...)):
    """One conversational turn with the Loki supervisor (T1).

    Body: {"question": str, "deep": bool, "scope": {"domain": str}?}. `deep` runs
    the agentic investigation loop (slower, more grounded). When `scope` names a
    domain, the bridge prepends that section's identity + live slice + repo/doctrine
    refs so the supervisor answers in-context and can cite real source. The model
    call blocks for up to ~60s, so it runs in a worker thread to keep the event
    loop free. Read-only: the supervisor answers, it does not act from here.
    """
    import supervisor_bridge

    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="missing question")
    deep = bool(body.get("deep"))

    # Resolve the scope preamble here (needs live state); the bridge stays free of
    # the watcher. Unknown/malformed scope degrades to an unscoped turn.
    scope = body.get("scope")
    preamble = None
    if isinstance(scope, dict) and scope.get("domain"):
        try:
            from deepdive import deep_payload

            payload = deep_payload(scope["domain"], _watcher(request).current())
            if payload:
                preamble = supervisor_bridge.scope_preamble(payload)
        except Exception:  # noqa: BLE001 — scoping is best-effort, never blocks the turn
            preamble = None

    return await asyncio.to_thread(supervisor_bridge.ask, question, deep, preamble)


# --- Phase 2: Web Push -------------------------------------------------------

@router.get("/push/vapid-key")
async def push_vapid_key():
    from push import vapid
    return {"applicationServerKey": vapid.application_server_key()}


@router.post("/push/subscribe")
async def push_subscribe(subscription: dict = Body(...)):
    from push import subscriptions
    if not subscription.get("endpoint"):
        raise HTTPException(status_code=400, detail="missing endpoint")
    total = subscriptions.add(subscription)
    return {"ok": True, "total": total}


@router.post("/push/unsubscribe")
async def push_unsubscribe(body: dict = Body(...)):
    from push import subscriptions
    endpoint = body.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="missing endpoint")
    subscriptions.remove(endpoint)
    return {"ok": True, "total": subscriptions.count()}


@router.post("/push/test")
async def push_test():
    """Operator-triggered delivery check (interrupt-class test payload)."""
    from push import sender
    result = sender.send_all({
        "title": "Monarch · test",
        "body": "Command Center push is wired up.",
        "severity": "info",
        "tag": "push_test",
    })
    return result


# --- Phase 3: gated control --------------------------------------------------

@router.get("/control/actions")
async def control_actions():
    """The closed enum of available actions (informational; no auth)."""
    return {"actions": registry.list_actions(), "dry_run_global": __import__("config").CONTROL_DRY_RUN}


@router.get("/control/verify", dependencies=[Depends(require_control_token)])
async def control_verify():
    """Token check: 200 only if a valid control token was presented."""
    return {"ok": True}


@router.get("/control/audit", dependencies=[Depends(require_control_token)])
async def control_audit(n: int = 50):
    return {"audit": audit.tail(n)}


@router.post("/control/{action}", dependencies=[Depends(require_control_token)])
async def control_run(action: str, body: dict = Body(default={})):
    """Execute a control action. Requires the control token (dependency),
    explicit confirmation, and audits every outcome."""
    if not registry.has(action):
        raise HTTPException(status_code=404, detail=f"unknown action: {action}")
    params = body.get("params") or {}
    dry_run = bool(body.get("dry_run"))
    confirm = bool(body.get("confirm"))

    # Real (non-dry-run) actions require explicit confirmation.
    if not dry_run and not confirm:
        audit.record(action, params, "denied", "confirmation required")
        raise HTTPException(status_code=400, detail="confirmation required (set confirm=true)")

    try:
        result = await registry.execute(action, params, dry_run=dry_run)
    except registry.ParamError as e:
        audit.record(action, params, "denied", f"param error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    audit.record(action, result.get("cleaned", params),
                 result.get("result", "error"), result.get("detail", ""),
                 dry_run=bool(result.get("dry_run")))
    return result


@router.get("/stream", dependencies=[Depends(require_read_token_sse)])
async def stream(request: Request):
    """Server-Sent Events. Emits an envelope on every accepted state change.

    Envelope: {"overview": <Overview>, "state": <raw state.json>}
    Heartbeat comment every 15s keeps proxies/Tailscale from idling the conn.
    """
    watcher = _watcher(request)

    async def gen():
        sub = watcher.subscribe()
        try:
            while True:
                try:
                    state = await asyncio.wait_for(sub.__anext__(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"        # SSE comment, ignored by client
                    continue
                if await request.is_disconnected():
                    break
                payload = {
                    "overview": derive_overview(state).model_dump(),
                    "state": state,
                    "routing": derive_routing(state),
                    "pending": enrich_pending(state),
                }
                yield f"data: {json.dumps(payload)}\n\n"
        finally:
            await sub.aclose()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
