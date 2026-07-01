import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import VitalsCard from "./components/cards/VitalsCard.jsx";
import EngineRoomCard from "./components/cards/EngineRoomCard.jsx";
import SpendCard from "./components/cards/SpendCard.jsx";
import MemoryMapCard from "./components/cards/MemoryMapCard.jsx";
import EventsCard from "./components/cards/EventsCard.jsx";
import ScheduleCard from "./components/cards/ScheduleCard.jsx";

const fixture = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../server/tests/fixtures/state.sample.json"
);
const state = JSON.parse(readFileSync(fixture, "utf8"));

const CARDS = { VitalsCard, EngineRoomCard, SpendCard, MemoryMapCard, EventsCard, ScheduleCard };

describe("rich cards render against the live fixture state", () => {
  for (const [name, C] of Object.entries(CARDS)) {
    it(`${name} renders real data without throwing`, () => {
      const html = renderToStaticMarkup(<C state={state} status="ok" />);
      expect(html.length).toBeGreaterThan(50);
    });
    it(`${name} survives empty/stale state`, () => {
      const html = renderToStaticMarkup(<C state={{}} status="unknown" />);
      expect(typeof html).toBe("string");
    });
    it(`${name} survives null-ish state`, () => {
      const html = renderToStaticMarkup(<C state={null} status="unknown" />);
      expect(typeof html).toBe("string");
    });
  }
});

describe("rich cards surface the right content", () => {
  it("Vitals shows the VRAM instrument", () => {
    const html = renderToStaticMarkup(<VitalsCard state={state} status="warn" />);
    expect(html).toContain("VRAM");
    expect(html).toContain("Substrate vitals");
  });
  it("Engine Room shows tier identifiers", () => {
    const html = renderToStaticMarkup(<EngineRoomCard state={state} status="ok" />);
    expect(html).toMatch(/T1/);
  });
  it("Memory Map shows the seven layers", () => {
    const html = renderToStaticMarkup(<MemoryMapCard state={state} status="ok" />);
    expect(html).toContain("L1");
    expect(html).toContain("L7");
  });
  it("Spend shows a today total", () => {
    const html = renderToStaticMarkup(<SpendCard state={state} status="ok" />);
    expect(html).toContain("spent today");
  });
  it("Events shows a severity tally", () => {
    const html = renderToStaticMarkup(<EventsCard state={state} status="ok" />);
    expect(html).toMatch(/info|warn|crit/);
  });
  it("Schedule shows the next-hour window", () => {
    const html = renderToStaticMarkup(<ScheduleCard state={state} status="ok" />);
    expect(html).toContain("Next 60 minutes");
  });
});
