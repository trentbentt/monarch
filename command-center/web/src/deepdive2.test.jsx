import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import MarkdownLite from "./components/deep/MarkdownLite.jsx";
import MemoryDeepDive from "./components/deep/MemoryDeepDive.jsx";
import CodebaseDeepDive from "./components/deep/CodebaseDeepDive.jsx";
import WorkflowsDeepDive from "./components/deep/WorkflowsDeepDive.jsx";

// ── MarkdownLite ─────────────────────────────────────────────────────────────
describe("MarkdownLite", () => {
  it("renders headings, code fences, inline code and lists", () => {
    const md = "# Title\n\npara with `code`\n\n```\nblock\n```\n\n- one\n- two";
    const html = renderToStaticMarkup(<MarkdownLite text={md} />);
    expect(html).toContain("md-h1");
    expect(html).toContain("md-code-inline");
    expect(html).toContain("md-pre");
    expect(html).toContain("md-list");
    expect(html).toContain("block");
  });
  it("never emits raw HTML from note content", () => {
    const html = renderToStaticMarkup(<MarkdownLite text={"<script>alert(1)</script>"} />);
    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain("&lt;script&gt;");
  });
});

// ── Memory deep-dive ─────────────────────────────────────────────────────────
const memPayload = {
  key: "memory", label: "Memory Map", status: "ok",
  manifest: {
    lede: "Seven-layer substrate.",
    capabilities: { vault_browser: true, semantic_search: false },
    suggestions: [],
  },
  detail: {
    facts: [{ label: "Layers", value: "7/7", status: "ok", sub: "reporting" }],
    items: {
      "L1 Redis": { status: "ok", layer: "L1", name: "Redis", cls: "Truth",
        locus: "redis :6379", what: "hot", fail: "§11.1", reporting: true, response_ms: 2 },
      "L3 pgvector": { status: "warn", layer: "L3", name: "pgvector", cls: "Index",
        locus: "pg", what: "semantic", fail: "§11.3", reporting: true },
    },
    notes: [],
  },
};

describe("MemoryDeepDive", () => {
  it("renders the doctrine-true ladder with class chips and facts", () => {
    const html = renderToStaticMarkup(<MemoryDeepDive payload={memPayload} />);
    expect(html).toContain("Redis");
    expect(html).toContain("pgvector");
    expect(html).toContain("cls-truth");
    expect(html).toContain("cls-index");
    expect(html).toContain("7/7");
  });
  it("survives an empty payload", () => {
    expect(typeof renderToStaticMarkup(<MemoryDeepDive payload={{}} />)).toBe("string");
  });
});

// ── Codebase deep-dive ───────────────────────────────────────────────────────
const cbPayload = {
  key: "codebase", label: "Codebase Map", status: "ok",
  manifest: { lede: "Structural memory.", suggestions: [] },
  detail: {
    facts: [{ label: "Indexed repos", value: "9", status: "ok", sub: "in L5" }],
    items: {
      "loki (substrate)": { status: "ok", name: "loki (substrate)", raw_name: "home-operator-projects-loki",
        nodes: 332, edges: 828, role: "the substrate" },
    },
    notes: [],
  },
};

describe("CodebaseDeepDive", () => {
  it("renders the repo strip with counts and facts", () => {
    const html = renderToStaticMarkup(<CodebaseDeepDive payload={cbPayload} />);
    expect(html).toContain("loki (substrate)");
    expect(html).toContain("332");
    expect(html).toContain("Indexed repos");
  });
  it("shows an unavailable state when no repos", () => {
    const html = renderToStaticMarkup(
      <CodebaseDeepDive payload={{ manifest: {}, detail: { facts: [], items: {}, notes: ["L5 read: down"] } }} />
    );
    expect(html).toContain("Structural index unavailable");
  });
});

// ── Workflows live panel (spec 4) ────────────────────────────────────────────
describe("WorkflowsDeepDive runs & grounding", () => {
  const base = {
    manifest: { lede: "wf", items: [] },
    detail: { facts: [], items: {}, notes: [] },
  };
  it("renders the live panel when runs/grounding present", () => {
    const payload = {
      ...base,
      detail: {
        ...base.detail,
        runs: [{ run_date: "2026-06-24", status: "complete", articles_used: 30, articles_fetched: 40, total_tokens: 1000 }],
        grounding: { verdicts: { confirmed: 9, refused: 1 }, corrob_rate: 0.91, total: 10, briefs: 3, sources: [{ discovered_via: "reuters", score: 0.9, survived: 9, total: 10 }] },
      },
    };
    const html = renderToStaticMarkup(<WorkflowsDeepDive payload={payload} />);
    expect(html).toContain("Runs &amp; grounding");
    expect(html).toContain("91%");
    expect(html).toContain("reuters");
  });
  it("shows the honest empty line when dormant", () => {
    const html = renderToStaticMarkup(<WorkflowsDeepDive payload={base} />);
    expect(html).toContain("No run data yet");
  });
});
