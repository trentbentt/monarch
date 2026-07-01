/**
 * 5-stop scientific colormap for brain activity visualization.
 * Maps normalized activity (0→1) to RGB.
 * From VISUAL_SPEC.md section 4.9.
 */
const STOPS: Array<[number, [number, number, number]]> = [
  [0.00, [10 / 255, 5 / 255, 25 / 255]],     // Deep indigo — baseline
  [0.20, [50 / 255, 10 / 255, 80 / 255]],     // Dark violet
  [0.45, [140 / 255, 25 / 255, 15 / 255]],    // Dark orange-red
  [0.70, [255 / 255, 107 / 255, 26 / 255]],   // Neural-orange #FF6B1A
  [1.00, [255 / 255, 220 / 255, 70 / 255]],   // Hot yellow peak
];

/** Interpolate the colormap at a given value t (0–1). Writes into out array at offset. */
export function sampleColormap(
  t: number,
  out: Float32Array,
  offset: number
): void {
  const clamped = Math.max(0, Math.min(1, t));

  // Find the two surrounding stops
  let lo = 0;
  for (let i = 1; i < STOPS.length; i++) {
    if (STOPS[i]![0] >= clamped) {
      lo = i - 1;
      break;
    }
  }
  const hi = Math.min(lo + 1, STOPS.length - 1);

  const [tLo, cLo] = STOPS[lo]!;
  const [tHi, cHi] = STOPS[hi]!;

  const range = tHi - tLo;
  const frac = range > 0 ? (clamped - tLo) / range : 0;

  out[offset] = cLo[0] + (cHi[0] - cLo[0]) * frac;
  out[offset + 1] = cLo[1] + (cHi[1] - cLo[1]) * frac;
  out[offset + 2] = cLo[2] + (cHi[2] - cLo[2]) * frac;
}
