/**
 * Types and loader for stc_activity.json (MNE source estimate data).
 * See CLAUDE.md for the frame→stage mapping.
 */

export interface ActivityFrame {
  lh: number[];
  rh: number[];
  time_ms: number;
}

export interface ActivityData {
  frames: {
    baseline: ActivityFrame;
    early: ActivityFrame;
    peak: ActivityFrame;
    late: ActivityFrame;
  };
  n_vertices_lh: number;
  n_vertices_rh: number;
}

let cached: ActivityData | null = null;

export async function loadActivityData(): Promise<ActivityData> {
  if (cached) return cached;
  const res = await fetch("/brain-assets/stc_activity.json");
  cached = (await res.json()) as ActivityData;
  return cached;
}

/**
 * Get the activity frame name for a given scroll stage.
 * Stage 0-1 → baseline, Stage 2 → early, Stage 3 → peak, Stage 4 → late, Stage 5 → baseline
 */
export function stageToFrame(
  stage: number
): keyof ActivityData["frames"] {
  if (stage <= 1) return "baseline";
  if (stage === 2) return "early";
  if (stage === 3) return "peak";
  if (stage === 4) return "late";
  return "baseline";
}
