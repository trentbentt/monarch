/**
 * Pure URL-rewriting helper shared by the runtime fetch/EventSource patches.
 * Kept free of browser globals so it can be unit-tested directly.
 */

/** Strip trailing slashes from a base URL. */
export function normalizeBase(base) {
  return (base || "").replace(/\/+$/, "");
}

/**
 * Rewrite an app-API path to the absolute backend base. Only `/api` and
 * `/api/...` are rewritten — every other path (local bundled assets like
 * `/brain-assets`, `/models`, fonts) is returned unchanged. With an empty base
 * (the browser PWA), the input is always returned unchanged.
 */
export function rewriteApiPath(url, base) {
  const b = normalizeBase(base);
  if (!b || typeof url !== "string") return url;
  if (url === "/api" || url.startsWith("/api/")) return b + url;
  return url;
}
