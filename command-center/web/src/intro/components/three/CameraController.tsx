"use client";

import { useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import type { CameraRigState } from "@/hooks/useCameraRig";

const POSITION_LERP = 0.06;
const LOOKAT_LERP = 0.06;

// Pre-allocated vectors — no per-frame heap allocation
const _lookAtVec = new THREE.Vector3();
const _posVec = new THREE.Vector3();

interface CameraControllerProps {
  rig: CameraRigState;
}

export function CameraController({ rig }: CameraControllerProps) {
  const { camera } = useThree();
  const currentLookAt = useRef(new THREE.Vector3(0, 0, 0));

  useFrame(() => {
    // Target position + mouse parallax offset
    _posVec.copy(rig.positionTarget.current);
    _posVec.x += rig.mouseOffset.current.x;
    _posVec.y -= rig.mouseOffset.current.y;

    // Lerp camera position
    camera.position.lerp(_posVec, POSITION_LERP);

    // Lerp lookAt target
    _lookAtVec.copy(rig.lookAtTarget.current);
    currentLookAt.current.lerp(_lookAtVec, LOOKAT_LERP);
    camera.lookAt(currentLookAt.current);
  });

  return null;
}
