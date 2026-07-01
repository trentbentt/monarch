import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { parseHash } from "./hooks/useHashRoute.js";
import GenericDeepDive from "./components/deep/GenericDeepDive.jsx";
import WorkflowsDeepDive from "./components/deep/WorkflowsDeepDive.jsx";
import RawSignal, { sliceFor } from "./components/deep/RawSignal.jsx";
import { panelMode, CARD_OVERVIEW } from "./components/deep/DeepDiveView.jsx";
import SupervisorChat from "./components/SupervisorChat.jsx";

// A deep-dive payload shaped exactly like /api/deep/workflows returns.
const payload = {
  key: "workflows",
  label: "Workflows",
  status: "warn",
  manifest: {
    lede: "The deterministic news pipeline and its evidence layer.",
    items: [
      {
        name: "news-pipeline",
        what: "Ingests feeds and verifies every claim.",
        repo: "/home/operator/projects/news-pipeline",
        doctrine: ["news_pipeline_architecture_v18.md"],
        stages: [
          { key: "ingest", label: "Ingest", what: "Pull feeds" },
          { key: "verify", label: "Verify", what: "Gate claims" },
        ],
      },
    ],
    doctrine: ["final_master_summary.md §E"],
    suggestions: ["How does verify work?"],
  },
  detail: {
    facts: [{ label: "Workflows", value: "3", status: "ok", sub: "registered" }],
    items: { "news-pipeline": { status: "warn", last_run: null, reporting: false } },
    notes: ["evidence-layer: repo not found"],
  },
};

describe("parseHash", () => {
  it("parses a deep-dive route", () => {
    expect(parseHash("#/deep/workflows")).toEqual({ name: "deep", key: "workflows" });
  });
  it("parses hyphenated keys", () => {
    expect(parseHash("#/deep/news-pipeline")).toEqual({ name: "deep", key: "news-pipeline" });
  });
  it("falls back to home for empty/unknown hashes", () => {
    expect(parseHash("")).toEqual({ name: "home", key: null });
    expect(parseHash("#/settings")).toEqual({ name: "home", key: null });
  });
});

describe("deep-dive content renders the payload", () => {
  it("GenericDeepDive shows lede, facts, items and notes", () => {
    const html = renderToStaticMarkup(<GenericDeepDive payload={payload} />);
    expect(html).toContain("deterministic news pipeline");
    expect(html).toContain("news-pipeline");
    expect(html).toContain("news_pipeline_architecture_v18.md");
    expect(html).toContain("repo not found");
  });

  it("WorkflowsDeepDive renders the stage rail", () => {
    const html = renderToStaticMarkup(<WorkflowsDeepDive payload={payload} />);
    expect(html).toContain("Ingest");
    expect(html).toContain("Verify");
    expect(html).toContain("wfp-rail");
  });

  it("renders without throwing on an empty payload", () => {
    expect(typeof renderToStaticMarkup(<GenericDeepDive payload={{}} />)).toBe("string");
    expect(typeof renderToStaticMarkup(<WorkflowsDeepDive payload={{}} />)).toBe("string");
  });
});

describe("RawSignal", () => {
  it("renders a kv-tree for a known domain slice", () => {
    const state = { memory: { layers: { L3: { health: "ok" } }, gc_proposals_total: 2 } };
    const html = renderToStaticMarkup(<RawSignal domainKey="memory" state={state} />);
    expect(html).toContain("layers");
    expect(html).toContain("gc_proposals_total");
  });
  it("shows an empty note for a domain with no slice", () => {
    const html = renderToStaticMarkup(<RawSignal domainKey="docs" state={{}} summary="see card" />);
    expect(html).toContain("No raw state slice");
  });
});

describe("panelMode — provider-less domains still get content", () => {
  it("a domain with a provider shows both tabs", () => {
    expect(panelMode("ready", false, false)).toEqual({ overview: true, raw: true, deadEnd: false });
  });
  it("a card-Overview domain (+slice) shows Overview AND Raw signal", () => {
    expect(panelMode("notfound", true, true)).toEqual({ overview: true, raw: true, deadEnd: false });
  });
  it("a provider-less domain WITH a raw slice but no card shows Raw signal only", () => {
    expect(panelMode("notfound", true, false)).toEqual({ overview: false, raw: true, deadEnd: false });
  });
  it("a provider-less domain with NO card and NO raw slice is the only true dead end", () => {
    expect(panelMode("notfound", false, false)).toEqual({ overview: false, raw: false, deadEnd: true });
  });
  it("shows nothing while still loading", () => {
    expect(panelMode("loading", true, true)).toEqual({ overview: false, raw: false, deadEnd: false });
  });
  it("the six card domains map to a card Overview; workflows/memory/docs do not", () => {
    for (const key of ["vitals", "tiers", "routing", "events", "schedule", "spend"]) {
      expect(CARD_OVERVIEW[key]).toBeTypeOf("function");
    }
    for (const key of ["workflows", "memory", "codebase", "authority", "docs"]) {
      expect(CARD_OVERVIEW[key]).toBeUndefined();
    }
  });
  it("the telemetry domains resolve a raw slice (so they reach Raw signal)", () => {
    const state = {
      resources: { vram: 1 }, hardware: { gpu: "x" }, tiers: { t1: {} }, workloads: {},
      health: { components: [] }, events: [], schedule: {}, decisions: {}, quotas: {}, operator: {},
    };
    for (const key of ["vitals", "tiers", "routing", "events", "schedule", "authority", "spend"]) {
      expect(Boolean(sliceFor(key, state))).toBe(true);
    }
  });
});

describe("SupervisorChat scope", () => {
  it("docked + scoped shows the section in its header and lede", () => {
    const html = renderToStaticMarkup(
      <SupervisorChat
        overview={{ overall: "ok" }}
        variant="dock"
        scope={{ domain: "workflows", label: "Workflows" }}
        suggestions={["How does verify work?"]}
      />
    );
    expect(html).toContain("Supervisor · Workflows");
    expect(html).toContain("Scoped to Workflows");
    expect(html).toContain("How does verify work?");
    expect(html).toContain("sup-dock");
  });

  it("unscoped keeps the default substrate console copy", () => {
    const html = renderToStaticMarkup(<SupervisorChat overview={{ overall: "ok" }} />);
    expect(html).toContain("Ask the substrate");
  });
});
