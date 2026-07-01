import { useEffect, useRef, useState } from "react";
import { apiFetch, getToken } from "../control";

const LAST_KEY = "cc:last-overview";

/**
 * Live connection to the backend.
 * - Primary: SSE /api/stream  ({overview, state} on every change)
 * - Fallback: poll /api/overview if SSE drops
 * - Offline shell: seeds from last cached overview so the UI renders something
 *   immediately even before the network responds.
 *
 * Returns { overview, state, conn } where conn is "live" | "polling" | "offline".
 */
export function useLiveState() {
  const seed = (() => {
    try {
      return JSON.parse(localStorage.getItem(LAST_KEY)) || null;
    } catch {
      return null;
    }
  })();

  const [overview, setOverview] = useState(seed);
  const [state, setState] = useState(null);
  const [routing, setRouting] = useState(null);
  const [pending, setPending] = useState([]);
  const [conn, setConn] = useState("offline");
  const pollRef = useRef(null);

  useEffect(() => {
    let es;
    let closed = false;

    const startPolling = () => {
      if (pollRef.current) return;
      setConn((c) => (c === "live" ? c : "polling"));
      const tick = async () => {
        try {
          // apiFetch attaches the token header when one is set, so reads keep
          // working when CC_REQUIRE_TOKEN_FOR_READS is enabled; harmless when not.
          const r = await apiFetch("/api/overview");
          if (r.ok) {
            const ov = await r.json();
            setOverview(ov);
            localStorage.setItem(LAST_KEY, JSON.stringify(ov));
            setConn("polling");
          } else {
            setConn("offline");
          }
        } catch {
          setConn("offline");
        }
      };
      tick();
      pollRef.current = setInterval(tick, 5000);
    };

    const stopPolling = () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };

    const connect = () => {
      try {
        // EventSource can't set headers, so the read-gate accepts the token as a
        // query param (server: require_read_token_sse). Sent only when a token is
        // set; the stream is otherwise open exactly as before.
        const t = getToken();
        es = new EventSource(t ? `/api/stream?token=${encodeURIComponent(t)}` : "/api/stream");
      } catch {
        startPolling();
        return;
      }
      es.onmessage = (ev) => {
        try {
          const { overview: ov, state: st, routing: rt, pending: pd } = JSON.parse(ev.data);
          setOverview(ov);
          setState(st);
          if (rt !== undefined) setRouting(rt);
          if (pd !== undefined) setPending(pd || []);
          localStorage.setItem(LAST_KEY, JSON.stringify(ov));
          stopPolling();
          setConn("live");
        } catch {
          /* ignore malformed frame */
        }
      };
      es.onerror = () => {
        // EventSource auto-reconnects; meanwhile fall back to polling.
        startPolling();
      };
    };

    connect();
    return () => {
      closed = true;
      if (es) es.close();
      stopPolling();
    };
  }, []);

  return { overview, state, routing, pending, conn };
}
