// Single source of truth for the entrance timeline. Used by the capture harness
// to render the video AND by playback to sync the live overlays (aurora, ground,
// ending) to video.currentTime — so they line up exactly with the baked frames.

export const FPS = 30;

export const BURST_HOLD = 3.2; // camera holds at the distant entry while the brain bursts in
export const JOURNEY = 14.0; // constant-velocity camera arc, progress 0 -> 1
export const END_HOLD = 1.6; // hold on the final pullback frame (clean tail for the ending)

export const DURATION = BURST_HOLD + JOURNEY + END_HOLD; // total seconds
export const TOTAL_FRAMES = Math.round(DURATION * FPS);

// Camera progress (0..1) as a pure function of elapsed seconds. Constant velocity
// through the journey; the camera's own 0.06 lerp supplies the ease-in/out feel.
export function progressFor(t) {
  if (t <= BURST_HOLD) return 0;
  if (t >= BURST_HOLD + JOURNEY) return 1;
  return (t - BURST_HOLD) / JOURNEY;
}
