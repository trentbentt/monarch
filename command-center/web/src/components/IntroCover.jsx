import "./IntroCover.css";

// Non-lazy, near-zero-cost opaque cover used as the Suspense fallback while the
// heavy 3D intro chunk downloads. It paints on frame 1 so the dashboard is never
// visible behind the entrance, and visually matches LoadingScreen's initial state
// so the hand-off to the real (asset-tracking) loader is seamless.
export default function IntroCover() {
  return (
    <div className="intro-cover">
      <div className="intro-cover-ring" />
      <span className="intro-cover-percent">0%</span>
      <div className="intro-cover-track">
        <div className="intro-cover-bar" />
      </div>
    </div>
  );
}
