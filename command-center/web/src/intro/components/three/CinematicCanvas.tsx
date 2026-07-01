"use client";

import { Suspense } from "react";
import { Canvas } from "@react-three/fiber";
import * as THREE from "three";
import { ParticleField } from "./ParticleField";
import { CorticalBrain } from "./CorticalBrain";
import { WireframeHead } from "./WireframeHead";
import { PostProcessing } from "./PostProcessing";
import { CameraController } from "./CameraController";
import { useCameraRig } from "@/hooks/useCameraRig";
import { useStarField } from "@/hooks/useStarField";

interface SceneProps {
  progressRef: React.MutableRefObject<number>;
}

export function Scene({ progressRef }: SceneProps) {
  const rig = useCameraRig(progressRef);
  const starField = useStarField();

  return (
    <>
      <CameraController rig={rig} />
      <ambientLight intensity={0.2} color="#ffffff" />
      <directionalLight position={[10, 5, 5]} intensity={1.6} color="#ffffff" />
      <directionalLight position={[-5, -10, -5]} intensity={1.5} color="#00D4FF" />
      <spotLight position={[0, 0, -8]} angle={0.6} penumbra={1} intensity={1.5} color="#ffffff" distance={15} />
      <ParticleField stageRef={rig.stage} starField={starField} />
      <Suspense fallback={null}>
        <CorticalBrain stage={rig.stage} progress={rig.progress} />
        <WireframeHead stageRef={rig.stage} />
      </Suspense>
      <PostProcessing stage={rig.stage} />
    </>
  );
}

interface CinematicCanvasProps {
  progressRef: React.MutableRefObject<number>;
}

export default function CinematicCanvas({ progressRef }: CinematicCanvasProps) {
  return (
    <div
      className="cinematic-bg"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        backgroundColor: "#04040F",
      }}
    >
      <Canvas
        style={{ background: "transparent" }}
        camera={{
          fov: 50,
          position: [0, 0, 6],
          near: 0.01,
          far: 200,
        }}
        // Cap DPR: on a Retina/HiDPI client (e.g. a Mac over Tailscale) an
        // uncapped dpr of 2 renders 4x the fragments and is the main cause of the
        // live-render jank that pushed this to a baked video. 1.5 stays crisp.
        dpr={[1, 1.5]}
        gl={{
          antialias: true,
          alpha: true,
          toneMapping: THREE.ACESFilmicToneMapping,
          toneMappingExposure: 1.15,
          outputColorSpace: THREE.SRGBColorSpace,
        }}
      >
        <Scene progressRef={progressRef} />
      </Canvas>
    </div>
  );
}
