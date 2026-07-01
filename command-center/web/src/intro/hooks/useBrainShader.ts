import { useMemo, useEffect, useRef } from "react";
import type { MutableRefObject } from "react";
import * as THREE from "three";

function extractTextures(scene: THREE.Object3D): {
  normalMap: THREE.Texture | null;
  roughnessMap: THREE.Texture | null;
  metalnessMap: THREE.Texture | null;
  aoMap: THREE.Texture | null;
} {
  const result = {
    normalMap: null as THREE.Texture | null,
    roughnessMap: null as THREE.Texture | null,
    metalnessMap: null as THREE.Texture | null,
    aoMap: null as THREE.Texture | null,
  };

  scene.traverse((child) => {
    if (child instanceof THREE.Mesh && child.material) {
      const mat = child.material as THREE.MeshStandardMaterial;
      if (mat.normalMap) result.normalMap = mat.normalMap;
      if (mat.roughnessMap) result.roughnessMap = mat.roughnessMap;
      if (mat.metalnessMap) result.metalnessMap = mat.metalnessMap;
      if (mat.aoMap) result.aoMap = mat.aoMap;
    }
  });

  return result;
}

export interface CustomUniforms {
  uStageActivation: { value: number };
  uOrange: { value: THREE.Color };
  uTime: { value: number };
  uFlowProgress: { value: number };
}

export function useBrainShader(lhScene: THREE.Object3D): {
  brainMaterial: THREE.MeshPhysicalMaterial;
  customUniforms: MutableRefObject<CustomUniforms>;
  restingEmissive: THREE.Color;
} {
  const customUniforms = useRef<CustomUniforms>({
    uStageActivation: { value: 0.0 },
    uOrange: { value: new THREE.Color("#FF0055") },
    uTime: { value: 0.0 },
    uFlowProgress: { value: 0.0 },
  });

  // MeshPhysicalMaterial — dark tech base with cyan sheen on fold edges
  const brainMaterial = useMemo(() => {
    const mat = new THREE.MeshPhysicalMaterial({
      color: new THREE.Color("#020A1A"),
      roughness: 0.50,
      metalness: 0.0,
      clearcoat: 0.0,
      sheen: 0.40,
      sheenColor: new THREE.Color("#00D4FF"),
      sheenRoughness: 0.5,
      iridescence: 0.3,
      iridescenceIOR: 1.6,
      emissive: new THREE.Color("#060d18"),
      emissiveIntensity: 0.05,
      // Holographic translucent pass. Depth is owned by a MeshBasicMaterial
      // pre-pass mesh so we can keep depthWrite off here and still
      // avoid intra-mesh back-face bleed-through ("muddy pink").
      transparent: true,
      opacity: 0,
      depthWrite: false,
      depthTest: true,
      side: THREE.FrontSide,
      envMapIntensity: 0.65,
    });

    mat.onBeforeCompile = (shader) => {
      // Link live uniform refs
      shader.uniforms.uStageActivation = customUniforms.current.uStageActivation;
      shader.uniforms.uOrange = customUniforms.current.uOrange;
      shader.uniforms.uTime = customUniforms.current.uTime;
      shader.uniforms.uFlowProgress = customUniforms.current.uFlowProgress;

      // ── Vertex: pass activation + local position to fragment ──
      shader.vertexShader = shader.vertexShader.replace(
        "#include <common>",
        `#include <common>
attribute float aActivation;
varying float vActivation;
varying vec3 vLocalPos;`,
      );
      shader.vertexShader = shader.vertexShader.replace(
        "#include <begin_vertex>",
        `#include <begin_vertex>
vActivation = aActivation;
vLocalPos = position;`,
      );

      // ── Fragment: inject into emissivemap_fragment (PBR-compliant) ──
      shader.fragmentShader = shader.fragmentShader.replace(
        "#include <common>",
        `#include <common>
uniform float uStageActivation;
uniform vec3 uOrange;
uniform float uTime;
uniform float uFlowProgress;
varying float vActivation;
varying vec3 vLocalPos;`,
      );
      // Stabilized Hologram V8 — baseline ambient + AP-axis band on top.
      shader.fragmentShader = shader.fragmentShader.replace(
        "#include <emissivemap_fragment>",
        `#include <emissivemap_fragment>
{
  float safeActivation = clamp(vActivation, 0.0, 1.0);
  float safeStage = clamp(uStageActivation, 0.0, 1.0);

  float viewDot = max(dot(normalize(vNormal), normalize(vViewPosition)), 0.0);
  float fresnel = pow(1.0 - viewDot, 1.5);

  float safeActClipped = clamp(safeActivation, 0.0, 1.0);

  // AP-axis sliding band (narrative flow, travels occipital → frontal)
  float apNorm = clamp((vLocalPos.y + 1.4) / 2.8, 0.0, 1.0);
  float apDist = apNorm - uFlowProgress;
  float apBand = exp(-pow(apDist / 0.28, 2.0));

  // Baseline holographic signal everywhere + peak along the travelling band.
  // 0.35 is the "ambient holo" preserving the v6 look; 0.65 is the band lift.
  float bandWeight = 0.50 + 0.50 * apBand;

  float fastFlow = sin(vLocalPos.z * 5.0 - uTime * 2.0) * 0.5 + 0.5;
  float slowBreath = sin(uTime * 0.8) * 0.15 + 0.85;

  // Data signal — real MNE activation, strong in occipital
  float dataSignal = pow(safeActClipped, 3.0) * fresnel * fastFlow * slowBreath * safeStage;

  // Flow signal — ungated on activation data, travels the full AP range
  float flowSignal = fresnel * fastFlow * slowBreath * safeStage * apBand;

  // Fresnel-aligned resting rim — geometrically exact, fades as activation takes over
  float rimFresnel = pow(1.0 - viewDot, 2.8);
  vec3 rimColor = vec3(0.0, 0.22, 0.42) * rimFresnel * (0.75 + slowBreath * 0.25) * (1.0 - safeStage * 0.75);
  totalEmissiveRadiance += rimColor;

  vec3 signalColor = uOrange * (dataSignal * bandWeight * 5.5 + flowSignal * 3.5);
  totalEmissiveRadiance += signalColor;
}`,
      );
    };

    // Force shader recompile whenever we change onBeforeCompile above.
    mat.customProgramCacheKey = () => "stabilized_hologram_v9_holographic";

    return mat;
  }, []);

  // Apply any textures extracted from the GLB. Both hemispheres share the same
  // MatCap/PBR pipeline, so the LH scene is sufficient.
  useEffect(() => {
    const textures = extractTextures(lhScene);
    if (textures.normalMap) brainMaterial.normalMap = textures.normalMap;
    if (textures.roughnessMap) brainMaterial.roughnessMap = textures.roughnessMap;
    if (textures.metalnessMap) brainMaterial.metalnessMap = textures.metalnessMap;
    if (textures.aoMap) brainMaterial.aoMap = textures.aoMap;
    brainMaterial.needsUpdate = true;
  }, [lhScene, brainMaterial]);

  const restingEmissive = useMemo(() => new THREE.Color("#060d18"), []);

  return { brainMaterial, customUniforms, restingEmissive };
}
