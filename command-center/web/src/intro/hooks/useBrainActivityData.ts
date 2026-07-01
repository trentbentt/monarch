import { useState, useEffect, useMemo } from "react";
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { loadActivityData, type ActivityData } from "@/lib/activityData";

const TARGET_RADIUS = 1.693;
const ACTIVITY_VERTEX_COUNT = 10242;

function buildActivityMapping(
  meshPositions: Float32Array,
  vertexCount: number,
  activityCount: number,
): Uint16Array {
  const mapping = new Uint16Array(vertexCount);

  for (let i = 0; i < Math.min(vertexCount, activityCount); i++) {
    mapping[i] = i;
  }

  if (vertexCount <= activityCount) return mapping;

  const srcPositions = new Float32Array(activityCount * 3);
  for (let i = 0; i < activityCount * 3; i++) {
    srcPositions[i] = meshPositions[i]!;
  }

  for (let i = activityCount; i < vertexCount; i++) {
    const px = meshPositions[i * 3]!;
    const py = meshPositions[i * 3 + 1]!;
    const pz = meshPositions[i * 3 + 2]!;

    let bestDist = Infinity;
    let bestIdx = 0;

    for (let j = 0; j < activityCount; j++) {
      const dx = px - srcPositions[j * 3]!;
      const dy = py - srcPositions[j * 3 + 1]!;
      const dz = pz - srcPositions[j * 3 + 2]!;
      const dist = dx * dx + dy * dy + dz * dz;
      if (dist < bestDist) {
        bestDist = dist;
        bestIdx = j;
      }
    }

    mapping[i] = bestIdx;
  }

  return mapping;
}

function extractFirstGeometry(scene: THREE.Object3D): THREE.BufferGeometry {
  let geo: THREE.BufferGeometry | null = null;
  scene.traverse((child) => {
    if (child instanceof THREE.Mesh && !geo) {
      geo = child.geometry;
    }
  });
  if (!geo) throw new Error("No mesh geometry found in GLB scene");
  return geo;
}

function prepareHemisphere(
  source: THREE.BufferGeometry,
  xOffsetFactor: number,
  keepUV: boolean,
): { geometry: THREE.BufferGeometry; vertexCount: number; mapping: Uint16Array } {
  const geo = source.clone();
  if (!geo.attributes.normal) geo.computeVertexNormals();

  // Strip to a canonical attribute set so mergeGeometries sees matching schemas.
  const keep = new Set(["position", "normal"]);
  if (keepUV) keep.add("uv");
  for (const key of Object.keys(geo.attributes)) {
    if (!keep.has(key)) geo.deleteAttribute(key);
  }

  // Center on origin.
  geo.computeBoundingBox();
  const center = new THREE.Vector3();
  geo.boundingBox!.getCenter(center);
  geo.translate(-center.x, -center.y, -center.z);
  geo.computeBoundingSphere();

  // Bake uniform scale + x offset directly into the geometry so the merged mesh
  // needs no per-hemisphere transform.
  const radius = geo.boundingSphere?.radius ?? 1;
  const scale = TARGET_RADIUS / radius;
  geo.scale(scale, scale, scale);
  geo.translate(xOffsetFactor * scale, 0, 0);

  // Per-vertex attributes the injected shader reads (filled later from activity data).
  const vertexCount = geo.attributes.position!.count;
  geo.setAttribute("activity", new THREE.BufferAttribute(new Float32Array(vertexCount), 1));
  geo.setAttribute("aActivation", new THREE.BufferAttribute(new Float32Array(vertexCount), 1));

  const positions = geo.attributes.position!.array as Float32Array;
  const mapping = buildActivityMapping(positions, vertexCount, ACTIVITY_VERTEX_COUNT);

  return { geometry: geo, vertexCount, mapping };
}

export interface MergedBrain {
  geometry: THREE.BufferGeometry;
  lhVertexCount: number;
  rhVertexCount: number;
  lhMapping: Uint16Array;
  rhMapping: Uint16Array;
}

export function useBrainActivityData(
  lhScene: THREE.Object3D,
  rhScene: THREE.Object3D,
): { merged: MergedBrain } {
  const [activityData, setActivityData] = useState<ActivityData | null>(null);

  useEffect(() => {
    loadActivityData().then(setActivityData);
  }, []);

  // Merged hemispheres → one geometry. Eliminates the object-level transparent-sort
  // flip between two near-centroid-matched meshes that was causing the flicker.
  const merged = useMemo((): MergedBrain => {
    const lhSrc = extractFirstGeometry(lhScene);
    const rhSrc = extractFirstGeometry(rhScene);

    // mergeGeometries requires identical attribute sets — keep UV only if both sides have it.
    const keepUV = lhSrc.attributes.uv != null && rhSrc.attributes.uv != null;

    const lh = prepareHemisphere(lhSrc, -0.035, keepUV);
    const rh = prepareHemisphere(rhSrc, 0.035, keepUV);

    const mergedGeo = mergeGeometries([lh.geometry, rh.geometry], false);
    if (!mergedGeo) {
      throw new Error(
        "mergeGeometries returned null — LH/RH attribute schemas don't match. " +
        "Check keepUV normalization and indexed-state consistency.",
      );
    }
    mergedGeo.computeBoundingBox();
    mergedGeo.computeBoundingSphere();

    return {
      geometry: mergedGeo,
      lhVertexCount: lh.vertexCount,
      rhVertexCount: rh.vertexCount,
      lhMapping: lh.mapping,
      rhMapping: rh.mapping,
    };
  }, [lhScene, rhScene]);

  // Fill the baseline `activity` attribute for both hemispheres.
  // LH occupies [0, lhVertexCount); RH occupies [lhVertexCount, total).
  useEffect(() => {
    if (!activityData) return;
    const frame = activityData.frames.baseline;
    const attr = merged.geometry.attributes.activity as THREE.BufferAttribute;
    const buf = attr.array as Float32Array;

    for (let i = 0; i < merged.lhVertexCount; i++) {
      const raw = frame.lh[merged.lhMapping[i]!];
      const v = typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
      buf[i] = v < 0 ? 0 : v > 1 ? 1 : v;
    }
    for (let i = 0; i < merged.rhVertexCount; i++) {
      const raw = frame.rh[merged.rhMapping[i]!];
      const v = typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
      buf[merged.lhVertexCount + i] = v < 0 ? 0 : v > 1 ? 1 : v;
    }
    attr.needsUpdate = true;
  }, [activityData, merged]);

  // Fill the peak `aActivation` attribute (drives the shader's holoSignal).
  useEffect(() => {
    if (!activityData) return;
    const frame = activityData.frames.peak;
    const attr = merged.geometry.attributes.aActivation as THREE.BufferAttribute;
    const buf = attr.array as Float32Array;

    for (let i = 0; i < merged.lhVertexCount; i++) {
      const raw = frame.lh[merged.lhMapping[i]!];
      const v = typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
      buf[i] = v < 0 ? 0 : v > 1 ? 1 : v;
    }
    for (let i = 0; i < merged.rhVertexCount; i++) {
      const raw = frame.rh[merged.rhMapping[i]!];
      const v = typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
      buf[merged.lhVertexCount + i] = v < 0 ? 0 : v > 1 ? 1 : v;
    }
    attr.needsUpdate = true;
  }, [activityData, merged]);

  return { merged };
}
