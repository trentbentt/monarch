// Phase 3 control client: token storage + gated action calls.

const TOKEN_KEY = "cc:control-token";
// Storage-mode preference (non-secret). MODE_KEY holds "persist" or "session",
// recording an explicit operator choice. Absent key defers to shell default:
// hardened session-only in browsers/PWAs (no persistent XSS target at rest),
// persistent in Tauri desktop shell (token already on disk; wiping storage buys
// nothing, only forces re-paste each launch). Session-only is now written
// explicitly to distinguish "chose session" from "no choice yet" (unset).
const MODE_KEY = "cc:control-token-mode";

// Web Storage may be absent (SSR / node test env). Degrade to no-token instead
// of throwing, so the shared apiFetch below is safe to call from anywhere.
function _ls() { try { return globalThis.localStorage ?? null; } catch { return null; } }
function _ss() { try { return globalThis.sessionStorage ?? null; } catch { return null; } }

/** True when the app runs inside the Tauri desktop shell — a local binary on
 * the same machine as the server, where the control token already sits on
 * disk in plain sight. Nothing is gained by wiping it from storage there. */
function _isDesktopShell() {
  try { return Boolean(globalThis.__TAURI_INTERNALS__); } catch { return false; }
}

export function isSessionOnly() {
  const mode = _ls()?.getItem(MODE_KEY);
  if (mode === "persist") return false;
  if (mode === "session") return true;
  // Unset: hardened default everywhere the device can be lost or shared
  // (browser, phone PWA); persistent on the desktop shell, which otherwise
  // makes the operator re-paste the token on every single launch.
  return !_isDesktopShell();
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
    // Record the choice explicitly: on the desktop shell the *unset* default
    // is now "persist", so clearing the key would silently flip the operator's
    // deliberate session-only choice on the next read.
    ls?.setItem(MODE_KEY, "session");
  } else {
    ls?.setItem(TOKEN_KEY, v);
    ss?.removeItem(TOKEN_KEY);
    ls?.setItem(MODE_KEY, "persist"); // explicit opt-in to persistence
  }
}

/**
 * Change where the CURRENT token is stored, without re-pairing.
 *
 * The mode used to be settable only on the pairing form — which hides once you
 * are paired — and `clearToken` deliberately drops the preference, so a re-pair
 * silently reverts to the hardened session-only default. That gave one shot at
 * the decision on a form you cannot get back to, and getting it wrong on a phone
 * means re-pasting a 43-character token every launch. This makes it a setting.
 *
 * No-op when nothing is paired: never write an empty credential.
 *
 * @param {boolean} sessionOnly  true = wipe on close, false = persist
 */
export function setPersistence(sessionOnly) {
  const t = getToken();
  if (!t) return;
  setToken(t, { sessionOnly });
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
