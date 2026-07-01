import { useRef, useEffect } from "react";
import gsap from "gsap";
import { ShinyButton } from "@/components/ui/ShinyButton";
import "./EndingOverlay.css";

// Ported verbatim from neuro-portfolio. The original final scene: a staggered
// reveal once the camera reaches the dignified pullback (progress > 0.88), with
// the shimmer ShinyButton. The button enters the dashboard (the original wired
// it to /command-center — same destination, now an in-app callback).
export default function EndingOverlay({ progressRef, onEnter }) {
  const nameRef = useRef(null);
  const subtitleRef = useRef(null);
  const ctaRef = useRef(null);
  const hasEverShown = useRef(false);
  const isShowing = useRef(false);
  const staggerTlRef = useRef(null);

  useEffect(() => {
    let rafId;

    const textEls = () => [nameRef.current, subtitleRef.current, ctaRef.current];

    const hideOverlay = () => {
      if (staggerTlRef.current) {
        staggerTlRef.current.kill();
        staggerTlRef.current = null;
      }
      gsap.to(textEls(), { opacity: 0, y: -20, duration: 0.5, ease: "power2.in", overwrite: true });
    };

    const showOverlay = () => {
      gsap.to(textEls(), { opacity: 1, y: 0, duration: 0.4, ease: "power2.out", overwrite: true });
    };

    const runStaggerAnimation = () => {
      const tl = gsap.timeline();
      staggerTlRef.current = tl;
      tl.fromTo(
        nameRef.current,
        { opacity: 0, y: 30 },
        { opacity: 1, y: 0, duration: 0.8, ease: "power3.out" },
        0,
      )
        .fromTo(
          subtitleRef.current,
          { opacity: 0, y: 30 },
          { opacity: 1, y: 0, duration: 0.8, ease: "power3.out" },
          0.2,
        )
        .fromTo(
          ctaRef.current,
          { opacity: 0, y: 20 },
          { opacity: 1, y: 0, duration: 0.8, ease: "power3.out" },
          0.4,
        );
    };

    const check = () => {
      const p = progressRef.current;
      if (p > 0.88 && !isShowing.current) {
        isShowing.current = true;
        if (!hasEverShown.current) {
          hasEverShown.current = true;
          runStaggerAnimation();
        } else {
          showOverlay();
        }
      } else if (p < 0.83 && isShowing.current) {
        isShowing.current = false;
        hideOverlay();
      }
      rafId = requestAnimationFrame(check);
    };
    rafId = requestAnimationFrame(check);

    return () => {
      cancelAnimationFrame(rafId);
    };
  }, [progressRef]);

  return (
    <div className="ending-overlay">
      <div className="ending-inner">
        <p ref={nameRef} className="ending-name" style={{ opacity: 0 }}>
          Monarch
        </p>
        <p ref={subtitleRef} className="ending-subtitle" style={{ opacity: 0 }}>
          Sovereign AI substrate
        </p>
        <div className="ending-cta-wrap">
          <ShinyButton
            ref={ctaRef}
            onClick={() => onEnter && onEnter()}
            className="ending-cta"
          >
            Enter
          </ShinyButton>
        </div>
      </div>
    </div>
  );
}
