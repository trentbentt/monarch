import { useRef, useEffect } from "react";
import { gsap } from "@/lib/gsap";
import { useProgress } from "@react-three/drei";
import "./LoadingScreen.css";

// Ported from neuro-portfolio. Tracks real asset load via drei useProgress,
// simulates a smooth fill, then fades out. Calls onDone after the fade so the
// orchestrator can begin the camera journey.
export default function LoadingScreen({ onDone }) {
  const containerRef = useRef(null);
  const percentRef = useRef(null);
  const barRef = useRef(null);
  const displayRef = useRef(0);
  const realDoneRef = useRef(false);
  const fadedRef = useRef(false);
  const mountTimeRef = useRef(0);
  const progressRef = useRef(0);
  const onDoneRef = useRef(onDone);
  const rafRef = useRef(null);
  const { progress } = useProgress();

  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    progressRef.current = progress;
  }, [progress]);

  useEffect(() => {
    mountTimeRef.current = Date.now();

    const tick = () => {
      const elapsed = (Date.now() - mountTimeRef.current) / 1000;
      if (progressRef.current >= 100 || elapsed > 3.0) realDoneRef.current = true;

      const sim = 1 - Math.exp(-elapsed * 0.9);
      const cap = realDoneRef.current ? 1.0 : Math.min(0.92, sim);
      displayRef.current += (cap - displayRef.current) * 0.15;
      const p = displayRef.current;

      if (percentRef.current) {
        percentRef.current.textContent = `${Math.round(p * 100)}%`;
      }
      if (barRef.current) {
        barRef.current.style.transform = `scaleX(${p})`;
      }

      if (p >= 0.998 && !fadedRef.current) {
        fadedRef.current = true;
        gsap.to(containerRef.current, {
          opacity: 0,
          duration: 0.7,
          delay: 0.2,
          ease: "power2.inOut",
          onComplete: () => {
            if (containerRef.current) containerRef.current.style.display = "none";
            if (onDoneRef.current) onDoneRef.current();
          },
        });
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <div ref={containerRef} className="loading-screen">
      <div className="loader-ring" />
      <span ref={percentRef} className="loader-percent">0%</span>
      <div className="loader-track">
        <div ref={barRef} className="loader-bar" />
      </div>
    </div>
  );
}
