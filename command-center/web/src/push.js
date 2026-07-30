// Web Push subscribe flow (client side).
//
// Every call goes through apiFetch so the control token rides along when one is
// paired: the /api/push/* routes are gated server-side (subscribe/unsubscribe
// decide where operator alerts land, and /push/test actuates), so a bare fetch()
// here would 401 the moment CC_REQUIRE_TOKEN_FOR_READS is enabled.
import { apiFetch } from "./control.js";

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function pushSupported() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export async function currentPermission() {
  return typeof Notification !== "undefined" ? Notification.permission : "unsupported";
}

export async function isSubscribed() {
  if (!pushSupported()) return false;
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  return !!sub;
}

export async function enablePush() {
  if (!pushSupported()) throw new Error("Push not supported on this browser");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Notification permission denied");

  const reg = await navigator.serviceWorker.ready;
  const keyResp = await apiFetch("/api/push/vapid-key");
  // Gated route: without this check a 401 body yields applicationServerKey
  // undefined, and the failure surfaces as an opaque atob() error much later.
  if (!keyResp.ok) throw new Error(
    keyResp.status === 401 ? "pair the control token first" : "vapid key unavailable");
  const { applicationServerKey } = await keyResp.json();

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(applicationServerKey),
    });
  }
  const r = await apiFetch("/api/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sub),
  });
  if (!r.ok) throw new Error("subscribe failed");
  return await r.json();
}

export async function sendTest() {
  const r = await apiFetch("/api/push/test", { method: "POST" });
  // /push/test takes the CONTROL token (it delivers to every device), so an
  // unpaired client gets 401. Without this the caller renders the error body as
  // "test: undefined sent, undefined failed".
  if (!r.ok) throw new Error(
    r.status === 401 ? "pair the control token first" : `test failed (${r.status})`);
  return await r.json();
}
