"use client";

import {
  EffectComposer,
  ChromaticAberration,
  Vignette,
  Noise,
} from "@react-three/postprocessing";
import { BlendFunction } from "postprocessing";
import { Vector2 } from "three";

const CA_OFFSET = new Vector2(0.0001, 0.0001);

interface PostProcessingProps {
  stage: React.MutableRefObject<number>;
}

/**
 * Bloom intentionally omitted. Any Bloom variant in this stack causes
 * one-frame whole-mesh vanishing on the brain (confirmed across
 * mipmapBlur on/off, fullscreen vs SelectiveBloom, transparent vs opaque
 * brain, multisampling 0/4, alpha true/false). The magenta glow is now
 * produced by:
 *   1. HDR emissive peaks in the brain shader (ACES tone maps into bloom)
 *   2. A diffuse back-side hull halo driven by the same uStageActivation
 * See CorticalBrain.tsx for both.
 */
export function PostProcessing(_props: PostProcessingProps) {
  return (
    <EffectComposer multisampling={4}>
      <ChromaticAberration
        blendFunction={BlendFunction.NORMAL}
        offset={CA_OFFSET}
        radialModulation={false}
        modulationOffset={0}
      />
      <Noise
        blendFunction={BlendFunction.SCREEN}
        opacity={0.01}
      />
      <Vignette
        offset={0.3}
        darkness={0.7}
        blendFunction={BlendFunction.NORMAL}
      />
    </EffectComposer>
  );
}
