"use client";

import { useEffect, useRef, useCallback } from "react";
import * as THREE from "three";
import { gsap } from "@/lib/gsap";

/* ── Camera keyframes — Occipital → Frontal arc ────────────────────────── */
/* Brain frontal lobe sits at world -Z (model Y=anterior → world -Z after    */
/* group's -PI/2 X rotation). Occipital sits at world +Z. Camera swings      */
/* from +Z (behind the head) through +X (side profile) to -Z (head-on face). */

const STAGES = [
  { pos: [0,   0,   6.0],  target: [0, 0, 0]   }, // 0: Entry — distant, stars framed
  { pos: [0,   0.2, 3.5],  target: [0, 0, 0.4] }, // 1: Occipital zoom-in — back of brain, close
  { pos: [1.8, 0.3, 3.2],  target: [0, 0, 0.2] }, // 2: Starting side swing (behind-right)
  { pos: [3.4, 0.3, 1.8],  target: [0, 0, 0]   }, // 3: Back-side quarter-turn
  { pos: [4.0, 0.3, 0],    target: [0, 0, 0]   }, // 4: Pure side profile — 90° around
  { pos: [3.4, 0.3, -1.8], target: [0, 0, 0]   }, // 5: Side-front — starting to see face
  { pos: [1.8, 0.3, -3.8], target: [0, 0, 0]   }, // 6: Approaching frontal — brain begins fade
  { pos: [0,   0.2, -6.58], target: [0, 0, 0]   }, // 7: Head-on frontal zoomed out — wire head
  { pos: [0,   0.2, -9.54], target: [0, 0, 0]   }, // 8: Continue — pull back 45%
  { pos: [0,   0.2, -12.0], target: [0, 0, 0]   }, // 9: Final dignified pullback — ending reveal
] as const;

const STAGE_COUNT = STAGES.length;

// Smooth camera path through the keyframe positions. Piecewise-linear interp
// between waypoints gives discontinuous velocity at every boundary (visible
// "lurch") and uneven speed because progress is constant but segment lengths
// differ ("lag" through short segments). A centripetal Catmull-Rom spline is
// C1-continuous (no kinks), and reading it with getPointAt() — arc-length
// parameterized — makes the camera travel at CONSTANT speed for the whole
// rotation. (lookAt stays linear below: the targets are nearly all [0,0,0], and
// duplicate points make a centripetal spline degenerate.)
const POS_CURVE = new THREE.CatmullRomCurve3(
  STAGES.map((s) => new THREE.Vector3(s.pos[0], s.pos[1], s.pos[2])),
  false,
  "centripetal",
);

const MOUSE_LERP = 0.04;
const MOUSE_MAX_X = 0.3;
const MOUSE_MAX_Y = 0.2;

export interface CameraRigState {
  positionTarget: React.MutableRefObject<THREE.Vector3>;
  lookAtTarget: React.MutableRefObject<THREE.Vector3>;
  mouseOffset: React.MutableRefObject<THREE.Vector2>;
  stage: React.MutableRefObject<number>;
  progress: React.MutableRefObject<number>;
}

export function useCameraRig(
  externalProgressRef: React.MutableRefObject<number>,
): CameraRigState {
  const positionTarget = useRef(new THREE.Vector3(STAGES[0].pos[0], STAGES[0].pos[1], STAGES[0].pos[2]));
  const lookAtTarget = useRef(new THREE.Vector3(STAGES[0].target[0], STAGES[0].target[1], STAGES[0].target[2]));
  const mouseOffset = useRef(new THREE.Vector2(0, 0));
  const mouseNormalized = useRef(new THREE.Vector2(0, 0));
  const stage = useRef(0);

  // Interpolate between two stages based on fractional progress
  const interpolateStage = useCallback((globalProgress: number) => {
    const u = Math.min(Math.max(globalProgress, 0), 1);
    const scaled = u * (STAGE_COUNT - 1);
    const idx = Math.min(Math.floor(scaled), STAGE_COUNT - 2);
    const t = scaled - idx;

    const from = STAGES[idx]!;
    const to = STAGES[idx + 1]!;

    // Position: smooth, constant-speed spline (no per-segment lurch).
    POS_CURVE.getPointAt(u, positionTarget.current);

    lookAtTarget.current.set(
      from.target[0] + (to.target[0] - from.target[0]) * t,
      from.target[1] + (to.target[1] - from.target[1]) * t,
      from.target[2] + (to.target[2] - from.target[2]) * t,
    );

    stage.current = Math.round(scaled);
    externalProgressRef.current = globalProgress;
  }, [externalProgressRef]);

  // Auto-play: follow the externally-driven progress ref each frame (the intro
  // sequence tweens externalProgressRef 0->1 over time — no scroll input).
  useEffect(() => {
    const onTick = () => interpolateStage(externalProgressRef.current);
    gsap.ticker.add(onTick);
    return () => gsap.ticker.remove(onTick);
  }, [interpolateStage, externalProgressRef]);

  // Mouse parallax
  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      mouseNormalized.current.set(
        (e.clientX / window.innerWidth) * 2 - 1,
        (e.clientY / window.innerHeight) * 2 - 1,
      );
    };

    window.addEventListener("mousemove", onMouseMove);
    return () => window.removeEventListener("mousemove", onMouseMove);
  }, []);

  // Lerp mouse offset each GSAP tick for smooth parallax
  useEffect(() => {
    const onTick = () => {
      mouseOffset.current.x += (mouseNormalized.current.x * MOUSE_MAX_X - mouseOffset.current.x) * MOUSE_LERP;
      mouseOffset.current.y += (mouseNormalized.current.y * MOUSE_MAX_Y - mouseOffset.current.y) * MOUSE_LERP;
    };

    gsap.ticker.add(onTick);
    return () => gsap.ticker.remove(onTick);
  }, []);

  return { positionTarget, lookAtTarget, mouseOffset, stage, progress: externalProgressRef };
}
