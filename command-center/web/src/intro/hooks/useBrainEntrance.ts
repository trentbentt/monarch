import { useEffect } from "react";
import type { MutableRefObject } from "react";
import * as THREE from "three";
import gsap from "gsap";

const RESTING_OPACITY = 0.45;

// GSAP "Lightning Core Burst" entrance — LOCKED, DO NOT MODIFY
export function useBrainEntrance(
  groupRef: MutableRefObject<THREE.Group | null>,
  sphereRef: MutableRefObject<THREE.Mesh | null>,
  sphereMatRef: MutableRefObject<THREE.MeshBasicMaterial | null>,
  brainMaterial: THREE.MeshPhysicalMaterial,
  restingEmissive: THREE.Color,
  hasAnimated: MutableRefObject<boolean>,
  entranceComplete: MutableRefObject<boolean>,
): void {
  useEffect(() => {
    const group = groupRef.current;
    const sphere = sphereRef.current;
    const sphereMat = sphereMatRef.current;
    if (!group || !sphere || !sphereMat) return;

    // HMR / Strict Mode remount — don't trap the brain at opacity 0.
    // Snap directly to the final holographic resting state (opacity 0.75, depthWrite off — depth pre-pass owns the z-buffer).
    if (hasAnimated.current) {
      group.position.set(0, 0, 0);
      group.rotation.z = 0;
      group.scale.set(1, 1, 1);
      brainMaterial.opacity = RESTING_OPACITY;
      brainMaterial.depthWrite = false;
      brainMaterial.emissiveIntensity = 0.05;
      brainMaterial.emissive.copy(restingEmissive);
      brainMaterial.needsUpdate = true;
      sphere.scale.set(0, 0, 0);
      sphereMat.opacity = 0;
      sphere.visible = false;
      entranceComplete.current = true;
      return;
    }
    hasAnimated.current = true;

    // Setup: brain invisible, energy core fully hidden so nothing appears before the delay.
    group.position.set(0, 0, 0);
    group.scale.set(0, 0, 0);
    group.rotation.z = -Math.PI * 24;
    brainMaterial.opacity = 0;
    brainMaterial.depthWrite = false;
    brainMaterial.emissiveIntensity = 10.0;
    brainMaterial.emissive.set("#00FFFF");
    sphere.scale.set(0, 0, 0);
    sphereMat.opacity = 0;

    const tl = gsap.timeline({
      delay: 0.4,
      onComplete: () => {
        // Guarantee final holographic resting state — depthWrite stays off; depth pre-pass owns z-buffer.
        brainMaterial.opacity = RESTING_OPACITY;
        brainMaterial.depthWrite = false;
        brainMaterial.needsUpdate = true;
        // Hand opacity control over to the scroll-driven useFrame lerp.
        entranceComplete.current = true;
      },
    });

    // ── Phase 0: Sphere snaps in (0–0.08s) ──
    tl.to(sphere.scale, {
      x: 0.15, y: 0.15, z: 0.15,
      duration: 0.08,
      ease: "power3.out",
    }, 0);
    tl.to(sphereMat, { opacity: 1, duration: 0.05 }, 0);

    // ── Phase 1: BZZZZ — charges hard with per-frame opacity jitter (0.1–1.1s) ──
    tl.to(sphere.scale, {
      x: 1.5, y: 1.5, z: 1.5,
      duration: 1.0,
      ease: "power4.in",
      onUpdate() { sphereMat.opacity = 0.5 + Math.random() * 0.5; },
      onComplete() { sphereMat.opacity = 1; },
    }, 0.1);

    // ── Phase 2: Detonation (1.1–1.22s) ──
    tl.to(sphere.scale, { x: 20, y: 20, z: 20, duration: 0.12, ease: "expo.out" }, 1.1);
    tl.to(sphereMat, {
      opacity: 0,
      duration: 0.3,
      ease: "power3.out",
      onComplete: () => { sphere.visible = false; },
    }, 1.4);

    // ── Phase 3: Brain emerges (1.1–2.1s) ──
    tl.to(group.scale, {
      x: 1, y: 1, z: 1,
      duration: 1.0,
      ease: "power3.out",
    }, 1.1);
    tl.to(brainMaterial, {
      opacity: RESTING_OPACITY,
      duration: 0.7,
      ease: "power2.out",
    }, 1.1);

    // ── Phase 4: Spin deceleration (1.25–3.75s) ──
    tl.to(group.rotation, {
      z: 0,
      duration: 2.5,
      ease: "power2.out",
    }, 1.25);

    // ── Phase 5: Emissive cool down (1.1–3.6s) ──
    tl.to(brainMaterial, {
      emissiveIntensity: 0.05,
      duration: 2.5,
      ease: "power3.out",
    }, 1.1);
    tl.to(brainMaterial.emissive, {
      r: restingEmissive.r,
      g: restingEmissive.g,
      b: restingEmissive.b,
      duration: 2.5,
      ease: "power3.out",
    }, 1.1);

    // ── Wub 1–4: scale micro-pulses as spin decelerates (after scale settles at 2.1s) ──
    tl.to(group.scale, { x: 1.06, y: 1.06, z: 1.06, duration: 0.07, ease: "power1.out" }, 2.2);
    tl.to(group.scale, { x: 1.0, y: 1.0, z: 1.0, duration: 0.30, ease: "power3.in" }, 2.27);

    tl.to(group.scale, { x: 1.045, y: 1.045, z: 1.045, duration: 0.07, ease: "power1.out" }, 2.7);
    tl.to(group.scale, { x: 1.0, y: 1.0, z: 1.0, duration: 0.25, ease: "power3.in" }, 2.77);

    tl.to(group.scale, { x: 1.03, y: 1.03, z: 1.03, duration: 0.06, ease: "power1.out" }, 3.15);
    tl.to(group.scale, { x: 1.0, y: 1.0, z: 1.0, duration: 0.22, ease: "power3.in" }, 3.21);

    tl.to(group.scale, { x: 1.015, y: 1.015, z: 1.015, duration: 0.05, ease: "power1.out" }, 3.55);
    tl.to(group.scale, { x: 1.0, y: 1.0, z: 1.0, duration: 0.18, ease: "power3.in" }, 3.6);

    // Subtle float after everything settles
    tl.to(group.position, {
      y: 0.06,
      duration: 3.0,
      ease: "sine.inOut",
      yoyo: true,
      repeat: -1,
    }, 4.0);
  }, [brainMaterial, restingEmissive]);
}
