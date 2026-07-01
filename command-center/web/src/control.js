// Phase 3 control client: token storage + gated action calls.

const TOKEN_KEY = "cc:control-token";
// Storage-mode preference (non-secret). Default is the HARDENED path:
// sessionStorage only — the token is wiped when the app closes and must be
// re-pasted each launch, so a persistent localStorage copy is never an
// XSS-exfiltration target at rest. The operator opts INTO persistence
// ("remember on this device"); MODE_KEY === "persist" records that choice.
const MODE_KEY = "cc:control-token-mode";

// Web Storage may be absent (SSR / node test env). Degrade to no-token instead
// of throwing, so the shared apiFetch below is safe to call from anywhere.
function _ls() { try { return globalThis.localStorage ?? null; } catch { return null; } }
function _ss() { try { return globalThis.sessionStorage ?? null; } catch { return null; } }

export function isSessionOnly() {
  return _ls()?.getItem(MODE_KEY) !== "persist";
}

export function getToken() {
  // Session-only tokens live in sessionStorage (cleared on app close); persistent
  // tokens in localStorage. Prefer the session copy, fall back to the persistent.
  return _ss()?.getItem(TOKEN_KEY) || _ls()?.getItem(TOKEN_KEY) || "";
}

export function setToken(t, { sessionOnly = isSessionOnly() } = {}) {
  const v = t || "";
  const ls = _ls(), ss = _ss();
  if (sessionOnly) {
    ss?.setItem(TOKEN_KEY, v);
    ls?.removeItem(TOKEN_KEY); // never leave a persistent copy at rest
    ls?.removeItem(MODE_KEY);  // session-only is the default
  } else {
    ls?.setItem(TOKEN_KEY, v);
    ss?.removeItem(TOKEN_KEY);
    ls?.setItem(MODE_KEY, "persist"); // explicit opt-in to persistence
  }
}

export function clearToken() {
  _ss()?.removeItem(TOKEN_KEY);
  _ls()?.removeItem(TOKEN_KEY);
  // Full unpair also drops the persist preference, so a re-pair defaults back to
  // the hardened sessionStorage path instead of silently re-persisting the token
  // to localStorage at rest (review B5).
  _ls()?.removeItem(MODE_KEY);
}

function authHeaders() {
  const t = getToken();
  return t ? { "X-CC-Token": t } : {};
}

/**
 * fetch() for the (optionally) token-gated read surface. Attaches the control
 * token when one is set so enabling CC_REQUIRE_TOKEN_FOR_READS on the server
 * Just Works (no re-paste prompt); harmless when reads are open — the server
 * ignores the header. Use this for the sensitive deep-dive reads.
 */
export function apiFetch(path, opts = {}) {
  return fetch(path, { ...opts, headers: { ...(opts.headers || {}), ...authHeaders() } });
}

export async function verifyToken(t) {
  const r = await fetch("/api/control/verify", { headers: { "X-CC-Token": t } });
  return r.ok;
}

export async function listActions() {
  const r = await fetch("/api/control/actions");
  return r.json();
}

/**
 * Run a control action.
 * @param {string} name   action id (closed enum on the server)
 * @param {object} params action params
 * @param {object} opts   { dryRun: bool, confirm: bool }
 * Returns { ok, status, body }.
 */
export async function runAction(name, params = {}, { dryRun = false, confirm = false } = {}) {
  const r = await fetch(`/api/control/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ params, dry_run: dryRun, confirm }),
  });
  let body = null;
  try {
    body = await r.json();
  } catch {
    body = null;
  }
  return { ok: r.ok, status: r.status, body };
}

export async function fetchAudit(n = 25) {
  const r = await fetch(`/api/control/audit?n=${n}`, { headers: authHeaders() });
  if (!r.ok) return { audit: [] };
  return r.json();
}
