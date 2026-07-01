"use client";

import { useRef, useEffect } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import gsap from "gsap";
import { TOTAL_STARS, type StarFieldBuffers } from "@/hooks/useStarField";

interface ParticleFieldProps {
  stageRef: React.MutableRefObject<number>;
  starField: StarFieldBuffers;
}

export function ParticleField({ stageRef, starField }: ParticleFieldProps) {
  const { positions, baseColors, colors, phases, speeds, shimmerTimes, shimmerAmps, texture } = starField;
  const matRef = useRef<THREE.PointsMaterial>(null);
  const pointsRef = useRef<THREE.Points>(null);
  const hasIgnited = useRef(false);
  const globalBrightnessRef = useRef(1.0);

  useEffect(() => {
    const mat = matRef.current;
    if (!mat) return;
    if (hasIgnited.current) {
      mat.opacity = 0.35;
      return;
    }
    hasIgnited.current = true;
    mat.opacity = 0.5;
    gsap.to(mat, {
      opacity: 0.35,
      duration: 3.0,
      ease: "power2.out",
      delay: 0.8,
    });
  }, []);

  useFrame(({ clock }) => {
    const geo = pointsRef.current?.geometry;
    if (!geo) return;
    const colAttr = geo.attributes.color as THREE.BufferAttribute;
    const buf = colAttr.array as Float32Array;
    const t = clock.elapsedTime;

    const isEnding = stageRef.current >= 8;
    const brightnessTarget = isEnding ? 1.6 : 1.0;
    globalBrightnessRef.current += (brightnessTarget - globalBrightnessRef.current) * 0.02;

    const shimmerCount = isEnding ? 10 : 5;
    for (let k = 0; k < shimmerCount; k++) {
      const i = Math.floor(Math.random() * TOTAL_STARS);
      shimmerTimes[i] = t;
      shimmerAmps[i]  = 1.8 + Math.random() * 2.2;
    }

    for (let i = 0; i < TOTAL_STARS; i++) {
      const twinkle = 0.7 + 0.3 * Math.sin(t * speeds[i]! + phases[i]!);
      const shimmer = shimmerAmps[i]! * Math.exp(-6 * (t - shimmerTimes[i]!));
      const brightness = (twinkle + shimmer) * globalBrightnessRef.current;
      buf[i * 3]     = baseColors[i * 3]!     * brightness;
      buf[i * 3 + 1] = baseColors[i * 3 + 1]! * brightness;
      buf[i * 3 + 2] = baseColors[i * 3 + 2]! * brightness;
    }
    colAttr.needsUpdate = true;
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial
        ref={matRef}
        size={0.2}
        sizeAttenuation
        map={texture}
        alphaMap={texture}
        alphaTest={0.001}
        transparent
        vertexColors
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        opacity={0.5}
      />
    </points>
  );
}
