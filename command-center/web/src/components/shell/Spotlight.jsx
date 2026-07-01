import { useRef } from "react";

/**
 * Cursor-follow spotlight surface (aceternity/magic-ui vocabulary, built native).
 * Tracks the pointer and writes --mx/--my onto itself; descendant .ic-card panels
 * read those to paint a faint cyan radial under the cursor, so the whole bento
 * grid reads as one illuminated instrument surface rather than separate tiles.
 *
 * Disabled for coarse pointers (touch) and reduced-motion — there the cards just
 * sit at their resting glass treatment.
 */
export default function Spotlight({ className = "", children }) {
  const ref = useRef(null);

  const onMove = (e) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  };

  return (
    <div ref={ref} className={`spotlight ${className}`} onPointerMove={onMove}>
      <div className="spotlight-glow" aria-hidden="true" />
      {children}
    </div>
  );
}
