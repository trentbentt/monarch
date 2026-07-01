import { useEffect, useState } from "react";
import { pushSupported, isSubscribed, enablePush, sendTest } from "../push.js";

/** Enable Web Push and send a delivery test. The phone's reason to exist. */
export default function PushControls() {
  const [supported, setSupported] = useState(true);
  const [subscribed, setSubscribed] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    setSupported(pushSupported());
    if (pushSupported()) isSubscribed().then(setSubscribed).catch(() => {});
  }, []);

  if (!supported) {
    return (
      <section className="panel">
        <h2>Notifications</h2>
        <div className="q-empty">Push not supported on this browser.</div>
      </section>
    );
  }

  const onEnable = async () => {
    setMsg("enabling…");
    try {
      const r = await enablePush();
      setSubscribed(true);
      setMsg(`subscribed (${r.total} device${r.total === 1 ? "" : "s"})`);
    } catch (e) {
      setMsg(e.message || "failed");
    }
  };

  const onTest = async () => {
    setMsg("sending test…");
    try {
      const r = await sendTest();
      setMsg(`test: ${r.sent} sent, ${r.failed} failed`);
    } catch {
      setMsg("test failed");
    }
  };

  return (
    <section className="panel">
      <h2>Notifications</h2>
      <div className="push-row">
        <button className="docs-btn" onClick={onEnable}>
          {subscribed ? "Re-subscribe" : "Enable push"}
        </button>
        {subscribed && <button className="docs-btn ghost" onClick={onTest}>Send test</button>}
        {msg && <span className="push-msg">{msg}</span>}
      </div>
      <div className="push-note">
        Interrupt-class alerts (thermal · security · spend-burst · RAM) bypass the
        overnight quiet window; other criticals fire only outside it.
      </div>
    </section>
  );
}
