/* Custom service worker (injectManifest): Workbox precache + offline shell + Web Push. */
import { precacheAndRoute } from "workbox-precaching";
import { registerRoute } from "workbox-routing";
import { NetworkFirst } from "workbox-strategies";

// vite-plugin-pwa injects the precache manifest (app shell) here.
precacheAndRoute(self.__WB_MANIFEST || []);

// Offline shell: cache the last good /api/overview so the dashboard renders a
// last-known view (with its own staleness banner) when monarch is unreachable.
registerRoute(
  ({ url }) => url.pathname.startsWith("/api/overview"),
  new NetworkFirst({ cacheName: "overview", networkTimeoutSeconds: 4 })
);

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: "Monarch", body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "Monarch Command Center";
  const options = {
    body: data.body || "",
    tag: data.tag || "monarch",
    data: { event_id: data.event_id, ts: data.timestamp },
    requireInteraction: data.severity === "critical",
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
      for (const c of cs) {
        if ("focus" in c) return c.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow("/");
    })
  );
});
