/**
 * Reachability watchdog — Layer A of the "is monarch alive?" story.
 *
 * useLiveState reports a `conn` of "live" | "polling" | "offline". "offline"
 * means the client can reach monarch through NEITHER the SSE stream NOR the
 * /api/overview poll — i.e. the box itself is unreachable (power loss, network
 * down, daemon+web both dead), not merely a stalled daemon (that is the separate
 * `overview.stale` banner).
 *
 * This module owns ONLY the in-app half: while the app is open, if monarch stays
 * unreachable past a threshold, raise a local notification + banner. It cannot
 * cover an outage while the app is closed — a dead monarch can't push, and iOS
 * suspends PWAs in the background. That gap is Layer B (the off-box dead-man's
 * switch, see scripts/deadman-ping.sh); the two are complementary.
 */

/**
 * Pure alert decision. Kept side-effect-free so it is trivially testable; the
 * hook owns the clock/flags and feeds these values in.
 *
 * @param {object} a
 * @param {boolean} a.everConnected  have we EVER reached monarch this session?
 *   (don't alarm during the very first connect, only on a *lost* connection)
 * @param {number|null} a.offlineSince  epoch-ms when conn first became "offline",
 *   or null while reachable
 * @param {number} a.now  epoch-ms now
 * @param {number} a.thresholdMs  how long unreachable before we alert
 * @returns {boolean}
 */
export function isReachabilityAlerting({ everConnected, offlineSince, now, thresholdMs }) {
  if (!everConnected) return false;
  if (offlineSince == null) return false;
  return now - offlineSince >= thresholdMs;
}

/**
 * Is this connection state an actual OUTAGE (monarch unreachable), as opposed to
 * merely not-serving-us?
 *
 * "unauthorized" is deliberately NOT an outage. When the read-gate
 * (CC_REQUIRE_TOKEN_FOR_READS) is armed and the client has no token, every read
 * returns 401 — monarch answered, so it is demonstrably up. Counting that as an
 * outage made an unpaired client display "the box may be down (power loss or
 * network)" and push a false unreachable notification about a healthy box.
 * The fix for that is pairing, not a power cycle, and the UI must say so.
 *
 * @param {string} conn  "live" | "polling" | "unauthorized" | "offline"
 * @returns {boolean}
 */
export function isOutageState(conn) {
  return conn !== "live" && conn !== "polling" && conn !== "unauthorized";
}

/**
 * Fire a local OS notification from the open PWA. iOS Safari PWAs do NOT support
 * the `new Notification()` constructor — notifications must go through the
 * service-worker registration — so prefer that and fall back to the constructor
 * on desktop browsers. No-op (resolves) when permission isn't granted or the
 * platform lacks Notifications, so callers never need to guard.
 */
export async function notifyLocal(title, body, tag = "monarch-unreachable") {
  try {
    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    const opts = { body, tag, renotify: false, requireInteraction: true };
    if ("serviceWorker" in navigator) {
      const reg = await navigator.serviceWorker.ready;
      await reg.showNotification(title, opts);
      return;
    }
    // eslint-disable-next-line no-new
    new Notification(title, opts);
  } catch {
    /* a notification failure must never bubble into the app */
  }
}
