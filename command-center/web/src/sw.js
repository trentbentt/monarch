/* Custom service worker (injectManifest): Workbox precache + offline shell + Web Push. */
import { precacheAndRoute, cleanupOutdatedCaches } from "workbox-precaching";
import { registerRoute } from "workbox-routing";
import { NetworkFirst } from "workbox-strategies";
import { clientsClaim } from "workbox-core";

// Take over immediately. `strategies: "injectManifest"` means THIS file owns the
// lifecycle — registerType "autoUpdate" only makes the registration check for a
// new worker, it does not make that worker activate. Without these, a new SW
// installs and then WAITS until every client of the old one closes, and an iOS
// home-screen PWA effectively never releases it: the phone kept serving a stale
// precached bundle, so a shipped fix simply never arrived. Observed in the
// field as "monarch has been offline a long time" plus a missing build stamp —
// both symptoms of running the very code that had already been fixed.
self.skipWaiting();
clientsClaim();

// Drop precaches from superseded builds so an old bundle can't be served back.
cleanupOutdatedCaches();

// vite-plugin-pwa injects the precache manifest (app shell) here.
precacheAndRoute(self.__WB_MANIFEST || []);

// Offline shell: cache the last good /api/overview so the dashboard renders a
// last-known view (with its own staleness banner) when monarch is unreachable.
registerRoute(
  ({ url }) => url.pathname.startsWith("/api/overview"),
  new NetworkFirst({ cacheName: "overview", networkTimeoutSeconds: 4 })
);

self.addEventListener("push", (event) => {
  // A payloadless push is the server's StoreFull liveness probe (sender.probe:
  // ttl=0, no data — only the delivery status matters). Showing it would turn
  // every capacity check into a phantom notification on live devices.
  if (!event.data) return;
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

// M165: the push service can rotate a subscription's endpoint at any time.
// The rotated-away endpoint is dead at the service but still holds a slot in
// the server store, and without this handler the device silently drops off
// alerts until the next app open re-subscribes. Re-subscribe now and tell the
// server both halves. Best-effort BY DESIGN: this fetch carries no control
// token (the SW has no access to the pairing), so under
// CC_REQUIRE_TOKEN_FOR_READS it may 401 — the next app open's enablePush()
// then re-registers, and the dead rotation no longer wedges the store because
// the StoreFull path prunes what the push service disowns.
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil((async () => {
    const oldSub = event.oldSubscription;
    let sub = event.newSubscription || null;
    if (!sub) {
      try {
        sub = await self.registration.pushManager.subscribe(
          (oldSub && oldSub.options) || { userVisibleOnly: true });
      } catch {
        return; // no options/permission to rebuild from — app-open path owns recovery
      }
    }
    const post = (path, body) =>
      fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).catch(() => {});
    await post("/api/push/subscribe", sub);
    if (oldSub && oldSub.endpoint && sub.endpoint !== oldSub.endpoint) {
      await post("/api/push/unsubscribe", { endpoint: oldSub.endpoint });
    }
  })());
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
