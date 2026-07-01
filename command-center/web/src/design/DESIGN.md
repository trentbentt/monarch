# Command Center — Design Language

**Direction:** a *precision instrument console* for monarch, a sovereign AI
substrate. Reference points: aviation/observatory gauges, mission consoles,
horology — not a generic SaaS dashboard. The operator trusts this surface to
read the health of a living system at a glance.

This is the binding contract for every card cluster. Derive every color, type,
and spacing decision from the tokens below. Do not invent new palettes,
typefaces, or shadow styles.

## Anti-generic guardrails (read first)

Avoid the three AI-default looks, especially **"near-black + single acid-green
accent"** — that is NOT our look. Our accent is **brass/champagne gold**, our
near-black is a cool *ink* (not pure black), and status colors are a *distinct*
desaturated triad. No purple gradients, no glassmorphism, no neon glows, no
emoji, no drop shadows. Depth comes from layered surfaces + hairline borders.

## Color (tokens in `tokens.css`)

| token | hex | use |
|-------|-----|-----|
| `--ink` | #0E1217 | app background (cool deep ink) |
| `--panel` | #161C24 | module surface |
| `--panel-2` | #1C2530 | raised / inset surface |
| `--hairline` | rgba(199,210,222,.10) | borders, dividers |
| `--frost` | #D4DCE6 | primary text (soft, never pure white) |
| `--muted` | #7C8AA0 | secondary text / labels |
| `--faint` | #4E5A6E | axes, tertiary, gauge tracks |
| `--brass` | #D8B45A | **signature accent only**: gauge arc, focus ring, wordmark, active rail. NEVER for status. |
| `--brass-dim` | #8A7438 | brass at rest / unfilled signature track |
| `--vital` | #57B894 | status OK (calm green — NOT acid) |
| `--caution` | #E0913C | status warn (amber) |
| `--alert` | #D85C52 | status crit (coral) |

Status colors appear only on status indicators (dots, bars, thresholds), used
sparingly. The brass accent is the one place we spend boldness.

## Type (self-hosted; tokens `--font-display/body/mono`)

- `--font-display` = **Space Grotesk** — eyebrows, card titles, the wordmark.
- `--font-body` = **IBM Plex Sans** — descriptions, prose, controls.
- `--font-mono` = **IBM Plex Mono** — ALL numeric readouts, units, IDs, timestamps,
  tabular data. This is the instrument-readout voice; lean on it.

Scale (use the classes/vars, don't hardcode px):
- eyebrow: 11px, `letter-spacing:.14em`, uppercase, `--muted`, display face.
- title: 14px / 600, `--frost`, display face.
- metric-lg: 30px, weight 300, mono, tabular-nums — the big instrument number.
- metric-sm: 18px mono tabular.
- body: 14px Plex Sans. caption: 12px `--muted`.

Always `font-variant-numeric: tabular-nums` on numbers so they don't jitter.

## Layout & shape

- Modules use the shared `Card` primitive: tracked eyebrow + status dot, then the
  instrument body, then supporting mono readouts. Hairline top-rail turns brass
  only when the module is the focus/critical.
- Radius `--r` 12px (modules), `--r-sm` 8px (inner). 1px hairline borders. 4px
  spacing grid (`--s1..--s6`). No drop shadows.
- Dense but breathable: this is data-rich, but whitespace and alignment carry it.

## Motion

Subtle and purposeful: 220ms ease on value/needle transitions, a slow pulse only
on `--alert`. Respect `@media (prefers-reduced-motion: reduce)` — disable
transitions/animation. No scattered hover effects.

## Signature element

The **VRAM radial gauge** (Vitals): a brass arc sweeping a `--faint` track, a
thin redline tick at the 80% baseline, the percentage as a metric-lg mono number
centered. It is the centerpiece instrument — the substrate's vital sign. Keep
every other card quieter so this reads as the hero.

## Shared primitives (in `src/design/primitives/`, import these — don't re-build)

- `Card` — module shell: props {eyebrow, title, status, rail, children, actions}.
- `Gauge` — radial dial {value, max, baselinePct?, label, unit, status}.
- `Meter` — horizontal bar {value, max, status, thresholdPct?, label}.
- `StackBar` — stacked segments {segments:[{label,value,color}], total}.
- `Sparkline` — SVG line {points:[n], status}.
- `Metric` — big readout {value, unit, label, size?}.
- `StatusDot` — {status} dot.
- `Cell` — small labeled status tile {label, status, value?, sub?}.
- `MiniTimeline` — {items:[{t, label, status}], windowLabel}.

Helpers in `lib.js`: `fmtAge(s)`, `fmtBytesMB(mb)`, `pct(a,b)`, `statusClass(s)`.

## Quality floor (non-negotiable)

Responsive (rich cards desktop ≥768px; phone keeps lean generic cards), visible
brass keyboard focus, reduced-motion respected, no console errors, accessible
contrast on `--frost`/`--muted` over `--panel`.

## Writing (copy)

Name things by what the operator controls/recognizes, plain and specific, active
voice, sentence case. Empty/again states give direction, not mood ("No proposals
— curated tier is clean."). A label labels; nothing does double duty.
