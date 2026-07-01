import { useRef, useEffect, useState } from "react";
import CinematicCanvas from "@/components/three/CinematicCanvas";
import AuroraBackground from "@/components/ui/AuroraBackground";
import ProceduralGroundBackground from "@/components/ui/ProceduralGroundBackground";
import LoadingScreen from "@/components/overlays/LoadingScreen";
import EndingOverlay from "@/components/overlays/EndingOverlay";
import "./IntroSequence.css";

// Faithful restoration of the neuro-portfolio brain entrance, driven by an
// automated scroll instead of the mouse wheel. No manual scroll, no added text.
//
// The original got its smoothness from ScrollTrigger `scrub: 2` (≈2s of inertial
// catch-up) layered on the camera lerp. We reproduce that here: progress advances
// at CONSTANT velocity (no easing → no speed-up/slow-down "lag"), and a scrub-style
// exponential smoother feeds the (unchanged) camera rig, ironing out the keyframe
// direction-changes. The same progress drives the aurora, the procedural ground,
// and the ending overlay — exactly as the original page did.

const DURATION = 7;       // seconds for the full constant-velocity journey (a bit faster than 8s; ~2.6x original 18s)
const SMOOTH_TAU = 0.4;   // inertial smoothing time-constant (mirrors scrub: 2 feel)
const START_DELAY = 1.4;  // let the brain "Lightning Core Burst" land before gliding

export default function IntroSequence({ onComplete }) {
  // One canonical, smoothed progress ref shared by every layer.
  const progressRef = useRef(0);
  const rawRef = useRef(0);
  const startedRef = useRef(false);
  const [fading, setFading] = useState(false);
  const fadingRef = useRef(false);

  const enter = () => {
    if (fadingRef.current) return;
    fadingRef.current = true;
    setFading(true);
    setTimeout(() => onComplete && onComplete(), 850);
  };

  // Loader finished fading → wait a beat (so the burst is seen) then begin.
  const beginAfterLoad = () => {
    setTimeout(() => {
      startedRef.current = true;
    }, START_DELAY * 1000);
  };

  // Hard-lock manual scrolling for the whole entrance — the sequence is fully
  // automated; the wheel/touch must not move anything.
  useEffect(() => {
    const prevHtml = document.documentElement.style.overflow;
    const prevBody = document.body.style.overflow;
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    return () => {
      document.documentElement.style.overflow = prevHtml;
      document.body.style.overflow = prevBody;
    };
  }, []);

  useEffect(() => {
    let rafId;
    let last = performance.now();
    const loop = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;

      if (startedRef.current) {
        rawRef.current = Math.min(1, rawRef.current + dt / DURATION);
      }
      // Exponential (frame-rate independent) smoothing toward the raw position.
      const k = 1 - Math.exp(-dt / SMOOTH_TAU);
      progressRef.current += (rawRef.current - progressRef.current) * k;

      rafId = requestAnimationFrame(loop);
    };
    rafId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafId);
  }, []);

  return (
    <div
      className={`intro ${fading ? "intro--out" : ""}`}
      role="dialog"
      aria-label="Command Center entrance"
    >
      <AuroraBackground progressRef={progressRef} />
      <CinematicCanvas progressRef={progressRef} />
      <ProceduralGroundBackground progressRef={progressRef} />
      <EndingOverlay progressRef={progressRef} onEnter={enter} />
      <LoadingScreen onDone={beginAfterLoad} />
    </div>
  );
}
