import { useRef, useEffect } from "react";
import { motion } from "framer-motion";
import "./AuroraBackground.css";

// Ported from neuro-portfolio (Tailwind → inline styles). Drifting aurora blobs,
// a cyan center pulse, and twinkling stars behind the brain. Fades out over the
// first ~18% of the journey (progress-driven).
const STARS = Array.from({ length: 60 }, (_, i) => ({
  id: i,
  x: (i * 17.3 + 11) % 100,
  y: (i * 31.7 + 7) % 100,
  peak: ((i * 7 + 3) % 8) * 0.1 + 0.1,
  duration: ((i * 13) % 30) * 0.1 + 2,
  delay: ((i * 19) % 50) * 0.1,
}));

const blob = (extra) => ({
  position: "absolute",
  borderRadius: "9999px",
  filter: "blur(44px)",
  willChange: "transform",
  ...extra,
});

export default function AuroraBackground({ progressRef, starCount = 24 }) {
  const wrapperRef = useRef(null);

  useEffect(() => {
    let rafId;
    const tick = () => {
      if (wrapperRef.current) {
        const p = progressRef.current;
        const opacity = Math.max(0, Math.min(1, 1 - p / 0.18));
        wrapperRef.current.style.opacity = String(opacity);
      }
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [progressRef]);

  return (
    <div
      ref={wrapperRef}
      style={{ position: "fixed", inset: 0, zIndex: 1, pointerEvents: "none", overflow: "hidden" }}
    >
      {/* Subtle center cyan pulse */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "radial-gradient(circle at 50% 50%, rgba(0,212,255,0.10) 0%, transparent 65%)",
          animation: "aurora-pulse 10s infinite",
        }}
      />

      {/* Blurred aurora blobs. NOTE: previously `mixBlendMode: "screen"`, which
          forced the compositor to re-blend three full-viewport blurred layers
          against EVERY frame of the playing brain video — the root cause of the
          start-of-sequence stutter. As plain source-over layers the blur is
          cached and compositing is cheap. (To restore the screen-over-video glow
          without the cost, bake the aurora into the video capture instead.) */}
      <motion.div
        style={{ position: "absolute", inset: 0 }}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1.5, ease: "easeInOut" }}
      >
        <motion.div
          style={blob({ top: "-25%", left: "-25%", width: "50%", height: "50%", opacity: 0.25, backgroundColor: "#163A6E" })}
          animate={{ x: [-50, 50, -50], y: [-20, 20, -20], scale: [1, 1.2, 1] }}
          transition={{ duration: 30, repeat: Infinity, repeatType: "mirror", ease: "easeInOut" }}
        />
        <motion.div
          style={blob({ bottom: "-25%", right: "-25%", width: "50%", height: "50%", opacity: 0.2, backgroundColor: "#0D2E5A" })}
          animate={{ x: [50, -50, 50], y: [20, -20, 20], scale: [1, 1.3, 1] }}
          transition={{ duration: 40, repeat: Infinity, repeatType: "mirror", ease: "easeInOut" }}
        />
        <motion.div
          style={blob({ top: "33%", left: "33%", width: "33%", height: "33%", opacity: 0.15, backgroundColor: "#161660" })}
          animate={{ x: [20, -20, 20], y: [-30, 30, -30], rotate: [0, 360, 0] }}
          transition={{ duration: 50, repeat: Infinity, repeatType: "mirror", ease: "easeInOut" }}
        />
      </motion.div>

      {/* Twinkling white star points */}
      {STARS.slice(0, starCount).map((star) => (
        <motion.div
          key={star.id}
          style={{
            position: "absolute",
            width: "1px",
            height: "1px",
            backgroundColor: "#fff",
            borderRadius: "9999px",
            left: `${star.x}vw`,
            top: `${star.y}vh`,
          }}
          animate={{ opacity: [0, star.peak, 0] }}
          transition={{ duration: star.duration, repeat: Infinity, delay: star.delay }}
        />
      ))}
    </div>
  );
}
