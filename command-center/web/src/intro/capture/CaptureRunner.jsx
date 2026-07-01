import { useRef, useState, useEffect } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { useProgress } from "@react-three/drei";
import * as THREE from "three";
import { Scene } from "@/components/three/CinematicCanvas";
import { gsap } from "@/lib/gsap";
import { createEncoder } from "./encodeVideo";
import { FPS, TOTAL_FRAMES, DURATION, progressFor } from "./introTimeline";

// Capture resolution. 1920x1080 @60 — object-fit:cover at playback handles any
// screen aspect. Rendered at dpr 1 so the backing buffer is exactly W x H.
const W = 1920;
const H = 1080;
const BITRATE = 5_000_000; // H.264 1080p30 — light enough for any remote client, grain hides banding

// Exposes R3F's manual-advance + the GL canvas to the parent so the capture loop
// (outside the Canvas) can step and read frames deterministically.
function Stepper({ stepRef, glRef }) {
  const advance = useThree((s) => s.advance);
  const gl = useThree((s) => s.gl);
  stepRef.current = advance;
  glRef.current = gl.domElement;
  return null;
}

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export default function CaptureRunner() {
  const progressRef = useRef(0);
  const stepRef = useRef(null);
  const glRef = useRef(null);
  const [status, setStatus] = useState("idle");
  const [pct, setPct] = useState(0);

  // Signal scene-asset readiness (brain/head GLBs) so a headless driver knows
  // when it's safe to start capturing.
  const { progress, active } = useProgress();
  useEffect(() => {
    if (!active && progress >= 100) window.__sceneReady = true;
  }, [active, progress]);

  async function record() {
    if (!stepRef.current || !glRef.current) return;
    setStatus("recording");

    const composite = document.createElement("canvas");
    composite.width = W;
    composite.height = H;
    const ctx = composite.getContext("2d");

    let enc;
    try {
      enc = await createEncoder({ width: W, height: H, fps: FPS, bitrate: BITRATE });
    } catch (e) {
      setStatus("error: " + e.message);
      window.__capError = e.message;
      console.error("[cap] error", e.message);
      return;
    }
    console.log("[cap] start", enc.info.kind, enc.info.codec);

    // Make gsap (the brain "Lightning Core Burst") deterministic: pause the root
    // and scrub it by virtual time each frame instead of letting the rAF ticker
    // advance it in real time.
    gsap.ticker.lagSmoothing(0);
    gsap.globalTimeline.pause();
    const base = gsap.globalTimeline.time();
    const startTs = performance.now();

    // The camera rig lerps a fixed amount PER FRAME (frame-count dependent, tuned
    // for 60fps). To keep the camera motion identical at a lower output fps, run
    // 60/fps lerp sub-steps per captured frame; only the last is encoded.
    const SUBSTEPS = Math.max(1, Math.round(60 / FPS));

    for (let f = 0; f <= TOTAL_FRAMES; f++) {
      const t = f / FPS;
      progressRef.current = progressFor(t);
      gsap.globalTimeline.time(base + t); // scrub burst to virtual time (time-based)
      for (let s = 0; s < SUBSTEPS; s++) {
        stepRef.current(startTs + (t + (s + 1) / (FPS * SUBSTEPS)) * 1000);
      }

      ctx.fillStyle = "#04040F";
      ctx.fillRect(0, 0, W, H);
      ctx.drawImage(glRef.current, 0, 0, W, H);
      enc.addFrame(composite, f);

      if (f % 15 === 0) {
        setPct(Math.round((f / TOTAL_FRAMES) * 100));
        // Yield so the tab stays responsive and the encoder drains its queue.
        await new Promise((r) => setTimeout(r, 0));
      }
    }

    setStatus("encoding…");
    const { blob, ext } = await enc.finish();
    gsap.globalTimeline.resume();
    download(blob, `brain-intro.${ext}`);
    setStatus(`done — ${(blob.size / 1e6).toFixed(1)} MB ${ext.toUpperCase()}`);
    setPct(100);
    window.__capExt = ext;
    window.__capDone = true;
    console.log("[cap] done", blob.size, ext);
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "#04040F", color: "#00D4FF", fontFamily: "monospace" }}>
      <div style={{ width: W, height: H, maxWidth: "100vw", maxHeight: "80vh", margin: "0 auto" }}>
        <Canvas
          frameloop="never"
          dpr={1}
          gl={{
            preserveDrawingBuffer: true,
            antialias: true,
            alpha: true,
            toneMapping: THREE.ACESFilmicToneMapping,
            toneMappingExposure: 1.15,
            outputColorSpace: THREE.SRGBColorSpace,
          }}
          camera={{ fov: 50, position: [0, 0, 6], near: 0.01, far: 200 }}
          style={{ width: "100%", height: "100%", background: "#04040F" }}
        >
          <Scene progressRef={progressRef} />
          <Stepper stepRef={stepRef} glRef={glRef} />
        </Canvas>
      </div>

      <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, padding: "16px 24px", display: "flex", gap: 20, alignItems: "center", background: "rgba(4,4,15,0.85)", borderTop: "1px solid rgba(0,212,255,0.25)" }}>
        <button
          id="rec"
          onClick={record}
          disabled={status === "recording" || status === "encoding…"}
          style={{ padding: "12px 28px", background: "#00D4FF", color: "#04040F", border: "none", borderRadius: 4, fontFamily: "monospace", fontWeight: 700, letterSpacing: "0.1em", cursor: "pointer", textTransform: "uppercase" }}
        >
          ● Record {Math.round(DURATION)}s
        </button>
        <span>{status} {status === "recording" ? `${pct}%` : ""}</span>
        <span style={{ opacity: 0.6, marginLeft: "auto" }}>{W}×{H} · {FPS}fps · downloads one file</span>
      </div>
    </div>
  );
}
