// Three sharp QRS-complex spikes per cycle — hospital-monitor aesthetic
export const ERP_SHAPE: readonly [number, number][] = [
  [0.000,  0.00],
  [0.095,  0.00],
  [0.110, -0.10],  // pre-deflection
  [0.128,  0.00],
  [0.135,  1.00],  // spike 1 — sharp QRS
  [0.143, -0.38],
  [0.152,  0.00],
  [0.175,  0.12],  // T-wave
  [0.210,  0.00],
  // flat run
  [0.415,  0.00],
  [0.430, -0.10],  // pre-deflection
  [0.448,  0.00],
  [0.455,  1.00],  // spike 2
  [0.463, -0.38],
  [0.472,  0.00],
  [0.495,  0.12],
  [0.530,  0.00],
  // flat run
  [0.735,  0.00],
  [0.750, -0.10],  // pre-deflection
  [0.768,  0.00],
  [0.775,  1.00],  // spike 3
  [0.783, -0.38],
  [0.792,  0.00],
  [0.815,  0.12],
  [0.850,  0.00],
  [1.000,  0.00],
];

export function interpolateERP(
  xNorm: number,
  shape: readonly [number, number][],
): number {
  const x = Math.max(0, Math.min(1, xNorm));
  for (let i = 0; i < shape.length - 1; i++) {
    const [x0, y0] = shape[i]!;
    const [x1, y1] = shape[i + 1]!;
    if (x >= x0 && x <= x1) {
      const range = x1 - x0;
      const t = range === 0 ? 0 : (x - x0) / range;
      return y0 + t * (y1 - y0);
    }
  }
  return 0;
}
