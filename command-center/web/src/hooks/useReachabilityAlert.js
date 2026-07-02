import { useEffect, useRef, useState } from "react";
import { isReachabilityAlerting, notifyLocal } from "../runtime/reachability.js";

// How long monarch must be fully unreachable before we raise the alarm.
// Overridable (minutes) via localStorage "cc:reach-threshold-min".
const DEFAULT_THRESHOLD_MS = 120_000; // 2 min

function thresholdMs() {
  const raw = Number(localStorage.getItem("cc:reach-threshold-min"));
  return raw > 0 ? raw * 60_000 : DEFAULT_THRESHOLD_MS;
}

/**
 * Watch the live-connection `conn` and, while the app is open, raise a local
 * notification + return an `alerting` flag once monarch has been unreachable
 * ("offline") continuously past the threshold. Clears the moment monarch is
 * reachable again.
 *
 * Layer A only (see runtime/reachability.js). Returns { alerting, offlineForMs }.
 */
export function useReachabilityAlert(conn) {
  const [alerting, setAlerting] = useState(false);
  const [offlineForMs, setOfflineForMs] = useState(0);

  const everConnected = useRef(false);
  const offlineSince = useRef(null);
  const notified = useRef(false);

  // Track connection transitions.
  useEffect(() => {
    if (conn === "live" || conn === "polling") {
      // Reachable again — reset everything and drop any active alarm.
      everConnected.current = true;
      offlineSince.current = null;
      notified.current = false;
      setAlerting(false);
      setOfflineForMs(0);
    } else if (offlineSince.current == null) {
      // First tick of an outage — start the clock.
      offlineSince.current = Date.now();
    }
  }, [conn]);

  // Poll the decision on a coarse cadence (the outage clock doesn't need to be
  // precise, and we don't want a re-render every second).
  useEffect(() => {
    const evaluate = () => {
      const since = offlineSince.current;
      if (since != null) setOfflineForMs(Date.now() - since);
      const now = Date.now();
      const shouldAlert = isReachabilityAlerting({
        everConnected: everConnected.current,
        offlineSince: since,
        now,
        thresholdMs: thresholdMs(),
      });
      if (shouldAlert && !notified.current) {
        notified.current = true;
        setAlerting(true);
        const mins = Math.round((now - since) / 60_000);
        notifyLocal(
          "Monarch unreachable",
          `No contact with monarch for ~${mins} min. It may be down (power loss / network).`,
        );
      }
    };
    evaluate();
    const id = setInterval(evaluate, 15_000);
    return () => clearInterval(id);
  }, []);

  return { alerting, offlineForMs };
}
