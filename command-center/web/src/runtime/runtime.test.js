import { describe, it, expect } from "vitest";
import { rewriteApiPath, normalizeBase } from "./urlRewrite.js";
import {
  shouldNotify,
  inOvernightWindow,
  buildNotification,
  parseHHMM,
} from "./notifyRules.js";

const BASE = "https://host.example-tailnet.ts.net:8443";

describe("urlRewrite", () => {
  it("rewrites /api paths to the absolute backend", () => {
    expect(rewriteApiPath("/api/overview", BASE)).toBe(`${BASE}/api/overview`);
    expect(rewriteApiPath("/api/stream", BASE)).toBe(`${BASE}/api/stream`);
    expect(rewriteApiPath("/api", BASE)).toBe(`${BASE}/api`);
  });

  it("preserves query strings", () => {
    expect(rewriteApiPath("/api/docs/search?q=x", BASE)).toBe(
      `${BASE}/api/docs/search?q=x`
    );
  });

  it("leaves local asset paths untouched", () => {
    expect(rewriteApiPath("/brain-assets/x.json", BASE)).toBe(
      "/brain-assets/x.json"
    );
    expect(rewriteApiPath("/models/brain.glb", BASE)).toBe("/models/brain.glb");
    // A path that merely contains 'api' but doesn't start with /api.
    expect(rewriteApiPath("/rapid/x", BASE)).toBe("/rapid/x");
  });

  it("is a no-op with an empty base (browser PWA)", () => {
    expect(rewriteApiPath("/api/overview", "")).toBe("/api/overview");
    expect(rewriteApiPath("/api/overview", undefined)).toBe("/api/overview");
  });

  it("normalizeBase strips trailing slashes", () => {
    expect(normalizeBase(`${BASE}/`)).toBe(BASE);
    expect(normalizeBase(`${BASE}///`)).toBe(BASE);
    expect(normalizeBase("")).toBe("");
  });
});

describe("notifyRules.shouldNotify", () => {
  const noPrefs = {};
  const day = new Date(2026, 5, 24, 14, 0); // 14:00 — outside any night window

  it("always notifies on interrupt-class events", () => {
    for (const type of [
      "gpu_thermal_critical",
      "security_alert",
      "spend_burst",
      "ram_exhaustion",
    ]) {
      expect(shouldNotify({ type, severity: "info" }, noPrefs, day)).toBe(true);
    }
  });

  it("notifies on critical severity outside the quiet window", () => {
    expect(shouldNotify({ type: "x", severity: "critical" }, noPrefs, day)).toBe(true);
    expect(shouldNotify({ type: "x", severity: "error" }, noPrefs, day)).toBe(true);
    expect(shouldNotify({ type: "x", severity: "crit" }, noPrefs, day)).toBe(true);
  });

  it("ignores non-critical, non-interrupt events", () => {
    expect(shouldNotify({ type: "x", severity: "info" }, noPrefs, day)).toBe(false);
    expect(shouldNotify({ type: "x", severity: "warn" }, noPrefs, day)).toBe(false);
    expect(shouldNotify({}, noPrefs, day)).toBe(false);
  });

  it("quiets critical events inside the overnight window but never interrupts", () => {
    const prefs = { overnight_window_start: "23:00", overnight_window_end: "07:00" };
    const night = new Date(2026, 5, 24, 3, 0); // 03:00 — inside the window
    expect(shouldNotify({ type: "x", severity: "critical" }, prefs, night)).toBe(false);
    // Interrupt classes still fire even at 3am.
    expect(shouldNotify({ type: "security_alert" }, prefs, night)).toBe(true);
  });
});

describe("notifyRules helpers", () => {
  it("parseHHMM handles valid and malformed input", () => {
    expect(parseHHMM("23:30")).toBe(23 * 60 + 30);
    expect(parseHHMM("00:00")).toBe(0);
    expect(parseHHMM("")).toBeNull();
    expect(parseHHMM("nonsense")).toBeNull();
    expect(parseHHMM(null)).toBeNull();
  });

  it("inOvernightWindow handles a window that wraps midnight", () => {
    const prefs = { overnight_window_start: "23:00", overnight_window_end: "07:00" };
    expect(inOvernightWindow(prefs, new Date(2026, 5, 24, 23, 30))).toBe(true); // 23:30
    expect(inOvernightWindow(prefs, new Date(2026, 5, 24, 2, 0))).toBe(true); // 02:00
    expect(inOvernightWindow(prefs, new Date(2026, 5, 24, 12, 0))).toBe(false); // noon
  });

  it("inOvernightWindow handles a same-day window", () => {
    const prefs = { overnight_window_start: "01:00", overnight_window_end: "06:00" };
    expect(inOvernightWindow(prefs, new Date(2026, 5, 24, 3, 0))).toBe(true);
    expect(inOvernightWindow(prefs, new Date(2026, 5, 24, 8, 0))).toBe(false);
  });

  it("inOvernightWindow returns false when prefs absent", () => {
    expect(inOvernightWindow({}, new Date())).toBe(false);
  });

  it("buildNotification produces a titled payload with fallbacks", () => {
    expect(buildNotification({ type: "security_alert", detail: "intrusion" })).toEqual({
      title: "Monarch · security_alert",
      body: "intrusion",
    });
    expect(buildNotification({ type: "spend_burst", severity: "critical", tier: "T3" })).toEqual({
      title: "Monarch · spend_burst",
      body: "critical event on T3",
    });
  });
});
