"use client";

import { useMemo } from "react";
import * as THREE from "three";

export const TOTAL_STARS = 2400;

export const LAYERS = [
  { pct: 0.70, rMin: 50, rMax: 80, oMin: 0.10, oMax: 0.30 },
  { pct: 0.20, rMin: 25, rMax: 50, oMin: 0.30, oMax: 0.60 },
  { pct: 0.10, rMin: 12, rMax: 25, oMin: 0.60, oMax: 1.00 },
] as const;

const STAR_WHITE = new THREE.Color("#E8F0FF");
const STAR_ICE_BLUE = new THREE.Color("#e0f2fe");
const STAR_WARM_ORANGE = new THREE.Color("#ffedd5");

function pickStarColor(roll: number): THREE.Color {
  if (roll < 0.80) return STAR_WHITE;
  if (roll < 0.90) return STAR_ICE_BLUE;
  return STAR_WARM_ORANGE;
}

export function createStarTexture(): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext("2d")!;
  const gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(0.3, "rgba(255,255,255,0.8)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(canvas);
}

export interface StarFieldBuffers {
  positions: Float32Array;
  baseColors: Float32Array;
  colors: Float32Array;
  phases: Float32Array;
  speeds: Float32Array;
  shimmerTimes: Float32Array;
  shimmerAmps: Float32Array;
  texture: THREE.CanvasTexture;
}

export function useStarField(): StarFieldBuffers {
  return useMemo(() => {
    const pos = new Float32Array(TOTAL_STARS * 3);
    const base = new Float32Array(TOTAL_STARS * 3);
    const col = new Float32Array(TOTAL_STARS * 3);
    const ph = new Float32Array(TOTAL_STARS);
    const sp = new Float32Array(TOTAL_STARS);
    const st = new Float32Array(TOTAL_STARS).fill(-999);
    const sa = new Float32Array(TOTAL_STARS);
    const tmpColor = new THREE.Color();

    let idx = 0;
    for (const layer of LAYERS) {
      const count = Math.round(TOTAL_STARS * layer.pct);
      for (let i = 0; i < count && idx < TOTAL_STARS; i++, idx++) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        const r = layer.rMin + Math.random() * (layer.rMax - layer.rMin);

        pos[idx * 3]     = r * Math.sin(phi) * Math.cos(theta);
        pos[idx * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
        pos[idx * 3 + 2] = r * Math.cos(phi);

        tmpColor.copy(pickStarColor(Math.random()));
        const opacity = layer.oMin + Math.random() * (layer.oMax - layer.oMin);
        const cr = tmpColor.r * opacity;
        const cg = tmpColor.g * opacity;
        const cb = tmpColor.b * opacity;
        base[idx * 3] = cr; base[idx * 3 + 1] = cg; base[idx * 3 + 2] = cb;
        col[idx * 3]  = cr; col[idx * 3 + 1]  = cg; col[idx * 3 + 2]  = cb;

        ph[idx] = Math.random() * Math.PI * 2;
        sp[idx] = 0.4 + Math.random() * 2.2;
      }
    }

    return {
      positions: pos,
      baseColors: base,
      colors: col,
      phases: ph,
      speeds: sp,
      shimmerTimes: st,
      shimmerAmps: sa,
      texture: createStarTexture(),
    };
  }, []);
}
