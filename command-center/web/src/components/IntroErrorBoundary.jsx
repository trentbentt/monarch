import { Component } from "react";

// The 3D intro is desktop-only eye-candy. It must NEVER be able to take down the
// operator dashboard: a failed asset load (e.g. a missing brain/head mesh), a
// WebGL context failure, or any runtime error inside the lazy IntroSequence is
// caught here and the app degrades straight to the console instead of unmounting
// the whole React tree into a blank screen.
export default class IntroErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, info) {
    // Surface it for future debugging — the dashboard still renders regardless.
    console.error("[command-center] intro sequence failed; skipping to dashboard:", error, info);
    if (this.props.onError) this.props.onError();
  }

  render() {
    if (this.state.failed) return null;
    return this.props.children;
  }
}
