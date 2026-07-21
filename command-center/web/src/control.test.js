import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { getToken, setToken, clearToken, isSessionOnly } from "./control.js";

// vitest runs in the node environment (no DOM), so stub the two Web Storage
// areas with simple in-memory maps. sessionStorage is the one a real browser
// wipes when the PWA is closed — we simulate that by clearing it.
function makeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    clear: () => m.clear(),
  };
}

beforeEach(() => {
  global.localStorage = makeStorage();
  global.sessionStorage = makeStorage();
});

const TOKEN = "cc:control-token";

describe("control token storage", () => {
  it("defaults to session-only storage (hardened: no persistent copy at rest)", () => {
    setToken("abc123");
    expect(isSessionOnly()).toBe(true);
    expect(sessionStorage.getItem(TOKEN)).toBe("abc123");
    expect(localStorage.getItem(TOKEN)).toBe(null); // not XSS-exfiltratable at rest
    expect(getToken()).toBe("abc123");
  });

  it("once persistence is opted into, a no-opts setToken stays persistent", () => {
    setToken("p1", { sessionOnly: false });
    expect(isSessionOnly()).toBe(false);
    setToken("p2"); // inherits the remembered persist preference
    expect(localStorage.getItem(TOKEN)).toBe("p2");
    expect(sessionStorage.getItem(TOKEN)).toBe(null);
  });

  it("session-only mode stores in sessionStorage and leaves no persistent copy", () => {
    setToken("xyz789", { sessionOnly: true });
    expect(isSessionOnly()).toBe(true);
    expect(sessionStorage.getItem(TOKEN)).toBe("xyz789");
    expect(localStorage.getItem(TOKEN)).toBe(null); // the whole point
    expect(getToken()).toBe("xyz789");
  });

  it("remembers the session-only preference and applies it by default on re-pair", () => {
    setToken("first", { sessionOnly: true });
    setToken("second"); // no opts → inherits the remembered preference
    expect(sessionStorage.getItem(TOKEN)).toBe("second");
    expect(localStorage.getItem(TOKEN)).toBe(null);
  });

  it("wipes the token when the app closes (sessionStorage cleared) but keeps the preference", () => {
    setToken("ephemeral", { sessionOnly: true });
    sessionStorage.clear(); // simulate closing the PWA
    expect(getToken()).toBe(""); // must re-paste
    expect(isSessionOnly()).toBe(true); // preference survives in localStorage
  });

  it("switching back to persistent clears the session copy and the preference", () => {
    setToken("eph", { sessionOnly: true });
    setToken("durable", { sessionOnly: false });
    expect(localStorage.getItem(TOKEN)).toBe("durable");
    expect(sessionStorage.getItem(TOKEN)).toBe(null);
    expect(isSessionOnly()).toBe(false);
  });

  it("clearToken fully unpairs — drops the token AND the persist preference", () => {
    setToken("gone", { sessionOnly: false }); // opted into persistence
    expect(isSessionOnly()).toBe(false);
    clearToken();
    expect(getToken()).toBe("");
    expect(localStorage.getItem(TOKEN)).toBe(null);
    expect(sessionStorage.getItem(TOKEN)).toBe(null);
    expect(isSessionOnly()).toBe(true); // re-pair defaults back to hardened sessionStorage
  });
});

describe("storage-mode default by shell (A2)", () => {
  // Storage is reset by the file-level beforeEach; only the shell marker
  // needs clearing, and it must not leak into other describe blocks.
  beforeEach(() => { delete globalThis.__TAURI_INTERNALS__; });
  afterEach(() => { delete globalThis.__TAURI_INTERNALS__; });

  it("browser/phone default stays hardened (session-only)", () => {
    expect(isSessionOnly()).toBe(true);
  });

  it("the Tauri desktop shell defaults to persistent", () => {
    globalThis.__TAURI_INTERNALS__ = {};
    expect(isSessionOnly()).toBe(false);
  });

  it("an explicit session choice survives on desktop", () => {
    globalThis.__TAURI_INTERNALS__ = {};
    setToken("tok-a", { sessionOnly: true });
    expect(isSessionOnly()).toBe(true);
    expect(localStorage.getItem("cc:control-token")).toBeNull();
  });

  it("an explicit persist choice survives in the browser", () => {
    setToken("tok-b", { sessionOnly: false });
    expect(isSessionOnly()).toBe(false);
    expect(localStorage.getItem("cc:control-token")).toBe("tok-b");
  });

  it("clearing returns to the shell default", () => {
    globalThis.__TAURI_INTERNALS__ = {};
    setToken("tok-c", { sessionOnly: true });
    expect(isSessionOnly()).toBe(true);
    clearToken();
    expect(isSessionOnly()).toBe(false);   // back to the desktop default
  });
});
