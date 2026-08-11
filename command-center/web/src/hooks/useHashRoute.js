import { useEffect, useState } from "react";

/**
 * Tiny hash router — no dependency, back-button works, deep-linkable, PWA-safe.
 *
 * Shapes: `#/deep/<key>`, `#/anatomy`, `#/anatomy/<node-id>`, `#/world`,
 * `#/world/<node-id>`.
 * Anything else (including empty) is {name: "home", key: null}.
 */
export function parseHash(hash) {
  const h = (hash || "").replace(/^#/, "");
  const m = h.match(/^\/deep\/([\w-]+)/);
  if (m) return { name: "deep", key: m[1] };
  // `#/anatomy/<node-id>` addresses one node, so a deep-dive Act section can
  // hand the operator to that node's drawer — where the audited action flow
  // already lives — instead of the deep-dive growing a second write surface.
  // Bare `#/anatomy` keeps its "no particular node" meaning.
  const a = h.match(/^\/anatomy\/([\w-]+)/);
  if (a) return { name: "anatomy", key: a[1] };
  if (/^\/anatomy/.test(h)) return { name: "anatomy", key: null };
  // `#/world/<id>` addresses one node so the world can be linked to and
  // returned to; bare `#/world` keeps its "no particular node" meaning.
  const w = h.match(/^\/world\/([\w-]+)/);
  if (w) return { name: "world", key: w[1] };
  if (/^\/world/.test(h)) return { name: "world", key: null };
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
