/**
 * Native OS notifications for the Tauri desktop app.
 *
 * The phone gets store-and-forward Web Push (server-side `push/bridge.py`). The
 * desktop app instead keeps the live SSE stream open and fires native OS
 * notifications (Notification Center / libnotify) on interrupt-class events
 * while it is running.
 *
 * The decision of *what* warrants a notification is a faithful mirror of the
 * server's `should_notify` (server/push/bridge.py): interrupt-class event types
 * ALWAYS notify; otherwise critical-severity events notify unless we are inside
 * the operator's overnight quiet window. Keep this in sync with that function
 * and with `CC_PUSH_INTERRUPT_TYPES` in server/config.py.
 *
 * This module is imported only inside Tauri (gated in main.jsx), so it never
 * runs in the browser PWA.
 */

import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import { shouldNotify, buildNotification } from "./notifyRules.js";

let started = false;

/**
 * Open a dedicated SSE connection and fire native notifications on qualifying
 * new events. Dedupes by event_id and primes on the first frame so historical
 * events are not replayed as notifications on launch (mirrors PushBridge).
 */
export async function startNativeNotifier() {
  if (started) return;
  started = true;

  let granted = await isPermissionGranted();
  if (!granted) {
    granted = (await requestPermission()) === "granted";
  }
  if (!granted) return; // operator declined; stay silent

  const seen = new Set();
  let primed = false;

  const connect = () => {
    let es;
    try {
      // EventSource is rewritten to the absolute backend by apiBase.js.
      es = new EventSource("/api/stream");
    } catch {
      setTimeout(connect, 5000);
      return;
    }

    es.onmessage = (ev) => {
      let envelope;
      try {
        envelope = JSON.parse(ev.data);
      } catch {
        return;
      }
      const state = envelope?.state || {};
      const events = state?.events?.log || [];
      const prefs = state?.operator?.preferences || {};
      const now = new Date();

      const fresh = events.filter((e) => !seen.has(e?.event_id));
      for (const e of events) seen.add(e?.event_id);

      if (!primed) {
        primed = true; // first snapshot: learn history, do not replay it
        return;
      }
      for (const e of fresh) {
        if (shouldNotify(e, prefs, now)) {
          const n = buildNotification(e);
          try {
            sendNotification(n);
          } catch {
            /* never let a delivery error kill the stream */
          }
        }
      }
    };

    es.onerror = () => {
      // Let EventSource auto-reconnect; if it gave up, it will be closed.
      if (es.readyState === EventSource.CLOSED) {
        setTimeout(connect, 5000);
      }
    };
  };

  connect();
}
