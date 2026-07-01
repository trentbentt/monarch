"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { TOTAL_STARS } from "@/hooks/useStarField";

interface NeuralWebProps {
  stageRef: React.MutableRefObject<number>;
  positions: Float32Array;
}

// Band-aware distance thresholds — proportional to each shell's inter-star spacing
function getThreshold(rSq: number): number {
  if (rSq < 30 * 30) return 6.0 * 6.0;    // foreground: tight clusters
  if (rSq < 55 * 55) return 12.0 * 12.0;  // midground
  return 20.0 * 20.0;                       // background: sparse but connected
}

const K = 5; // max neighbors per star

export function NeuralWeb({ stageRef, positions }: NeuralWebProps) {
  const matRef = useRef<THREE.LineBasicMaterial>(null);
  const opacityRef = useRef(0);

  const linePositions = useMemo(() => {
    const pairs: number[] = [];

    for (let i = 0; i < TOTAL_STARS; i++) {
      const ix = positions[i * 3]!;
      const iy = positions[i * 3 + 1]!;
      const iz = positions[i * 3 + 2]!;
      const rSqI = ix * ix + iy * iy + iz * iz;
      const threshold = getThreshold(rSqI);

      const neighbors: Array<{ distSq: number; j: number }> = [];

      for (let j = i + 1; j < TOTAL_STARS; j++) {
        const jx = positions[j * 3]!;
        const jy = positions[j * 3 + 1]!;
        const jz = positions[j * 3 + 2]!;
        const dx = ix - jx;
        const dy = iy - jy;
        const dz = iz - jz;
        const distSq = dx * dx + dy * dy + dz * dz;
        if (distSq < threshold) {
          neighbors.push({ distSq, j });
        }
      }

      neighbors.sort((a, b) => a.distSq - b.distSq);
      const limit = Math.min(K, neighbors.length);
      for (let k = 0; k < limit; k++) {
        const { j } = neighbors[k]!;
        pairs.push(
          ix, iy, iz,
          positions[j * 3]!, positions[j * 3 + 1]!, positions[j * 3 + 2]!,
        );
      }
    }

    return new Float32Array(pairs);
  }, [positions]);

  useFrame(({ clock }) => {
    const target = stageRef.current >= 8 ? 0.05 : 0.0;
    opacityRef.current += (target - opacityRef.current) * 0.015;

    if (matRef.current) {
      const pulse = Math.sin(clock.elapsedTime * 0.8) * 0.5 + 0.5;
      matRef.current.opacity = opacityRef.current * (0.75 + 0.25 * pulse);
    }
  });

  return (
    <lineSegments>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[linePositions, 3]} />
      </bufferGeometry>
      <lineBasicMaterial
        ref={matRef}
        color="#00D4FF"
        transparent
        opacity={0}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
      />
    </lineSegments>
  );
}
