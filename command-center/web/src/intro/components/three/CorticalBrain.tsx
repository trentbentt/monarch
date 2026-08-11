"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { useBrainActivityData } from "@/hooks/useBrainActivityData";
import { useBrainShader } from "@/hooks/useBrainShader";
import { useBrainEntrance } from "@/hooks/useBrainEntrance";

// (useDraco, useMeshopt) are BOTH false, at every call site, deliberately.
//
// drei wires a Draco loader and a Meshopt decoder into every GLTFLoader by
// default (Gltf.js:14/21), and the Meshopt decoder instantiates its wasm the
// moment the loader is built. Under the dashboard's `script-src 'self'` that
// throws a CompileError on every first visit — M157. Both meshes here declare
// extensionsUsed: [] and extensionsRequired: [], so neither decoder has
// anything to decode: the wasm was pure cost, and the honest fix is to not ask
// for it rather than to widen the policy for a capability nothing uses.
//
// If a mesh here is ever re-exported WITH meshopt or draco compression, these
// flags must change AND web/e2e/csp-wasm.e2e.test.mjs has to be re-reasoned —
// at that point the capability stops being dead weight and the trade is real.
// The useGLTF calls below carry the same flags; they must not drift apart.
useGLTF.preload("/brain-assets/brain_lh.glb", false, false);
useGLTF.preload("/brain-assets/brain_rh.glb", false, false);

const ACTIVATION_LERP = 0.03;
const FLOW_LERP = 0.08;
const OPACITY_LERP = 0.04;
const RESTING_OPACITY = 0.65;

interface CorticalBrainProps {
  stage: React.MutableRefObject<number>;
  progress: React.MutableRefObject<number>;
}

export function CorticalBrain({ stage, progress }: CorticalBrainProps) {
  const groupRef = useRef<THREE.Group>(null);
  const sphereRef = useRef<THREE.Mesh>(null);
  const sphereMatRef = useRef<THREE.MeshBasicMaterial>(null);
  const hasAnimated = useRef(false);
  const entranceComplete = useRef(false);
  const depthPrePassRef = useRef<THREE.Mesh>(null);

  // Same (useDraco, useMeshopt) as the preloads above — see the note there.
  const lhGltf = useGLTF("/brain-assets/brain_lh.glb", false, false);
  const rhGltf = useGLTF("/brain-assets/brain_rh.glb", false, false);

  const { merged } = useBrainActivityData(lhGltf.scene, rhGltf.scene);
  const { brainMaterial, customUniforms, restingEmissive } = useBrainShader(lhGltf.scene);

  useBrainEntrance(
    groupRef,
    sphereRef,
    sphereMatRef,
    brainMaterial,
    restingEmissive,
    hasAnimated,
    entranceComplete,
  );

  // Scroll-driven activation, flow progression, and brain → wire-head crossfade.
  // No autorotation — camera does the work now, brain stays fixed so the
  // occipital-to-frontal flow lines up with the camera arc.
  useFrame((_, delta) => {
    // Drive kinetic pulse uniform — wraps at 3600s to keep float precision.
    customUniforms.current.uTime.value =
      (customUniforms.current.uTime.value + delta) % 3600;

    // Lerp activation uniform — independent of GSAP entrance.
    const activationTarget = stage.current >= 2 ? 1.0 : 0.0;
    customUniforms.current.uStageActivation.value = THREE.MathUtils.lerp(
      customUniforms.current.uStageActivation.value,
      activationTarget,
      ACTIVATION_LERP,
    );

    // Lerp flow progress toward scroll — magenta band slides occipital → frontal.
    customUniforms.current.uFlowProgress.value = THREE.MathUtils.lerp(
      customUniforms.current.uFlowProgress.value,
      progress.current,
      FLOW_LERP,
    );

    // Brain fades out at stage >= 7. Progress gate replaces entranceComplete
    // so timing doesn't depend on the GSAP onComplete callback firing.
    if (progress.current > 0.05) {
      const opacityTarget = stage.current >= 7 ? 0.0 : RESTING_OPACITY;
      brainMaterial.opacity = THREE.MathUtils.lerp(
        brainMaterial.opacity,
        opacityTarget,
        OPACITY_LERP,
      );
      // Hide depth pre-pass when brain is invisible so its z-footprint doesn't
      // occlude the wire head behind the brain silhouette.
      if (depthPrePassRef.current) {
        depthPrePassRef.current.visible = brainMaterial.opacity > 0.02;
      }
    }

  });

  return (
    <>
      {/* Energy core — glowing cyan sphere for entrance detonation.
          renderOrder 2 keeps it above brain during flash.
          DoubleSide lets camera see inner wall once sphere envelops it. */}
      <mesh ref={sphereRef} scale={0} renderOrder={2}>
        <sphereGeometry args={[0.5, 32, 32]} />
        <meshBasicMaterial
          ref={sphereMatRef}
          color="#00FFFF"
          transparent
          opacity={0}
          depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>
      <group position={[0, 0.136, 0]}>
        <group
          ref={groupRef}
          position={[0, 0, 0]}
          rotation={[-Math.PI / 2, 0, 0]}
        >
          {/* Depth pre-pass — writes z only (no color). Lets the transparent
              brain pass below z-test against the nearest front-facing triangle
              and eliminates intra-mesh sort flicker / muddy-pink bleed-through. */}
          <mesh
            ref={depthPrePassRef}
            geometry={merged.geometry}
            renderOrder={0}
            frustumCulled={false}
          >
            <meshBasicMaterial
              colorWrite={false}
              depthWrite={true}
              side={THREE.FrontSide}
            />
          </mesh>

          <mesh
            geometry={merged.geometry}
            renderOrder={1}
            frustumCulled={false}
            userData={{ activation: 0.0, signalLocation: [0, 0, 0] }}
          >
            <primitive
              object={brainMaterial}
              attach="material"
              depthWrite={false}
              depthTest={true}
              side={THREE.FrontSide}
            />
          </mesh>
        </group>
      </group>
    </>
  );
}
