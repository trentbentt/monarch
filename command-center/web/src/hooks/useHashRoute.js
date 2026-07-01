import { useEffect, useState } from "react";

/**
 * Tiny hash router — no dependency, back-button works, deep-linkable, PWA-safe.
 *
 * Recognises one shape today: `#/deep/<key>` → {name: "deep", key}. Anything
 * else (including empty) is {name: "home", key: null}. Components navigate with
 * the exported `navigate()` helper or plain anchors to `#/deep/<key>`.
 */
export function parseHash(hash) {
  const h = (hash || "").replace(/^#/, "");
  const m = h.match(/^\/deep\/([\w-]+)/);
  if (m) return { name: "deep", key: m[1] };
  return { name: "home", key: null };
}

export function navigate(to) {
  // to: "" | "/deep/<key>". Assigning location.hash pushes a history entry, so
  // the browser back button returns to wherever the operator came from.
  window.location.hash = to;
}

export function useHashRoute() {
  const [route, setRoute] = useState(() =>
    parseHash(typeof window !== "undefined" ? window.location.hash : "")
  );

  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return route;
}
