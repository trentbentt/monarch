"""Command Center backend entry point.

Binds 127.0.0.1 ONLY (Tailscale is the sole remote path). Starts the state.json
watcher on a lifespan hook and mounts the read-only API.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import config
from api.routes import router as api_router
from push.bridge import PushBridge
from reader.state_watcher import StateWatcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Resolve the control token once. Surface only a fingerprint — never the
    # value — so the secret can't leak into logs. Pair clients by reading the
    # 0600 file directly: cat runtime/control_token.txt
    import hashlib
    from control.auth import get_token
    token = get_token()
    fp = hashlib.sha256(token.encode()).hexdigest()[:12]
    print(f"[command-center] control token ready "
          f"(fingerprint sha256:{fp}; value at {config.CONTROL_TOKEN_PATH}; "
          f"dry_run={config.CONTROL_DRY_RUN})", flush=True)

    watcher = StateWatcher()
    await watcher.start()
    app.state.watcher = watcher
    bridge = PushBridge(watcher)
    await bridge.start()
    app.state.push_bridge = bridge
    try:
        yield
    finally:
        await bridge.stop()
        await watcher.stop()


app = FastAPI(title="Command Center", version="0.1.0", lifespan=lifespan)

# Cross-origin callers:
#   * the Vite dev server (local development), and
#   * the native Tauri desktop app, whose bundled webview serves assets from a
#     local origin (``tauri://localhost`` on macOS, ``http://tauri.localhost``
#     on Linux/Windows) and reaches this backend over Tailscale.
# The prod PWA is served same-origin, so it needs no entry here. CORS is a
# browser policy, not a network boundary — the bind stays loopback-only and the
# sole remote path remains Tailscale. No credentials are used (token is a
# header), so this does not widen authenticated access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173", "http://localhost:5173",
        "tauri://localhost", "http://tauri.localhost",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Security headers on every response. The Tauri desktop app pins a strict CSP in
# its webview config, but the served PWA (FileResponse below) shipped with NONE —
# so any script-injection vector on the PWA origin (a compromised dependency, a
# future dangerouslySetInnerHTML) could read the operator token from storage and
# drive the control plane with nothing to blunt it (review H7). Mirror the Tauri
# CSP for the same-origin app + API ('self' covers the SSE/fetch/worker/manifest
# the PWA uses) and add the standard hardening headers. setdefault() so a handler
# that needs a per-response override still wins.
_CSP = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
    "media-src 'self' blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
    "script-src 'self'; worker-src 'self' blob:; child-src 'self' blob:; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    for key, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


app.include_router(api_router)


# --- Serve the built PWA same-origin with the API ----------------------------
# When the frontend is built (web/dist), serve it from this origin so the app,
# its service worker, the manifest, and /api all share ONE origin — required for
# install + Web Push. Front this with HTTPS (e.g. `tailscale serve`) and the PWA
# is installable and notifications work. Absent a build, the API runs alone (dev
# uses the Vite server instead). Override the location with CC_WEB_DIST.
_WEB_DIST = Path(os.environ.get("CC_WEB_DIST", str(Path(__file__).parent.parent / "web" / "dist")))

if _WEB_DIST.is_dir():
    _DIST_ROOT = _WEB_DIST.resolve()

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        """Serve a built asset if it exists, else fall back to index.html for the
        client-side (hash) routes. /api/* is owned by the router above and never
        reaches here. Path-traversal is refused."""
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (_DIST_ROOT / full_path).resolve()
        if candidate != _DIST_ROOT and _DIST_ROOT not in candidate.parents:
            raise HTTPException(status_code=404)  # escaped the dist tree
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST_ROOT / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.BIND_HOST, port=config.BIND_PORT)
