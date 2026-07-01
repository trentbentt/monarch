"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";

useGLTF.preload("/models/head_woman_basemesh.glb");

// Wire head encases the brain (brain TARGET_RADIUS = 1.8), slightly larger.
const TARGET_HEAD_RADIUS = 3.001;
const FADE_SPEED = 0.018;
const MAX_OPACITY = 0.45;
const FILL_OPACITY = 0.2;

interface PreparedHead {
  geometry: THREE.BufferGeometry;
  scale: number;
}

function prepareHead(geo: THREE.BufferGeometry): PreparedHead {
  const clone = geo.clone();
  clone.computeBoundingBox();
  const center = new THREE.Vector3();
  clone.boundingBox!.getCenter(center);
  clone.translate(-center.x, -center.y, -center.z);
  clone.computeBoundingSphere();
  clone.computeVertexNormals();
  const radius = clone.boundingSphere?.radius ?? 1;
  return { geometry: clone, scale: TARGET_HEAD_RADIUS / radius };
}

interface WireframeHeadProps {
  stageRef: React.MutableRefObject<number>;
}

export function WireframeHead({ stageRef }: WireframeHeadProps) {
  const { scene } = useGLTF("/models/head_woman_basemesh.glb");
  const outerRef = useRef<THREE.Mesh>(null);
  const innerRef = useRef<THREE.Mesh>(null);

  const { geometry, scale } = useMemo<PreparedHead>(() => {
    let geo: THREE.BufferGeometry | null = null;
    scene.traverse((child) => {
      if (child instanceof THREE.Mesh && !geo) geo = child.geometry;
    });
    if (!geo) {
      return { geometry: new THREE.SphereGeometry(1, 22, 18), scale: TARGET_HEAD_RADIUS };
    }
    return prepareHead(geo);
  }, [scene]);

  // Phases in at stage >= 5, full by stage 6 (head-on frontal).
  // No auto-rotation — the camera arcs around a static head, matching the brain.
  useFrame(() => {
    const target = stageRef.current >= 6 && stageRef.current < 8 ? 1 : 0;
    if (outerRef.current) {
      const mat = outerRef.current.material as THREE.MeshBasicMaterial;
      mat.opacity = THREE.MathUtils.lerp(mat.opacity, target * MAX_OPACITY, FADE_SPEED);
      mat.visible = mat.opacity > 0.01;
    }
    if (innerRef.current) {
      const mat = innerRef.current.material as THREE.MeshBasicMaterial;
      mat.opacity = THREE.MathUtils.lerp(mat.opacity, target * FILL_OPACITY, FADE_SPEED);
      mat.visible = mat.opacity > 0.01;
    }
  });

  return (
    <group scale={scale} rotation={[Math.PI / 2, Math.PI, 0]} position={[0, -1.293, 0]}>
      <mesh ref={outerRef} geometry={geometry}>
        <meshBasicMaterial color="#00D4FF" wireframe transparent opacity={0} />
      </mesh>
      <mesh ref={innerRef} geometry={geometry} scale={0.97}>
        <meshBasicMaterial color="#001833" transparent opacity={0} side={THREE.BackSide} />
      </mesh>
    </group>
  );
}
