import { useEffect, useState } from "react";
import { getToken, setToken, clearToken, verifyToken, fetchAudit, isSessionOnly, setPersistence } from "../control.js";
import { BUILD_SHA, BUILD_VERSION, DESKTOP_VERSION, syncState } from "../buildinfo.js";
import BuildStamp from "./BuildStamp.jsx";

/** Control pairing (token) + substrate actuators + audit trail. */
export default function ControlPanel({ openConfirm }) {
  const [token, setTok] = useState(getToken());
  const [paired, setPaired] = useState(false);
  const [msg, setMsg] = useState("");
  const [audit, setAudit] = useState([]);
  const [sessionOnly, setSessionOnly] = useState(isSessionOnly());
  const [serverBuild, setServerBuild] = useState(null);
  const [readDenials, setReadDenials] = useState(0);

  const refreshAudit = () => fetchAudit(15).then((d) => {
    setAudit(d.audit || []);
    setReadDenials(d.read_denials || 0);
  });

  useEffect(() => {
    if (getToken()) verifyToken(getToken()).then((ok) => {
      setPaired(ok);
      if (ok) { refreshAudit(); setSessionOnly(isSessionOnly()); }
    });
    // Ungated on purpose — the build stamp must render even when this client is
    // unpaired or stale, which is exactly when you need to read it.
    //
    // The sha goes UP because only the server holds the repo and can turn it
    // into a distance from HEAD (M49). Sent by every client, not just the
    // desktop one: the value is the caller's own build identity, and one code
    // path here is worth more than a branch that only the harder-to-test client
    // exercises. Encoded because it reaches a subprocess argument on the far
    // side — the server allowlists it to hex, and this is the second lock.
    fetch(`/api/version?client_sha=${encodeURIComponent(BUILD_SHA)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setServerBuild)
      .catch(() => setServerBuild(null));
  }, []);

  const pair = async () => {
    setMsg("verifying…");
    const ok = await verifyToken(token.trim());
    if (ok) {
      setToken(token.trim(), { sessionOnly });
      setPaired(true);
      setMsg("paired");
      refreshAudit();
    } else {
      setPaired(false);
      setMsg("invalid token");
    }
  };

  const unpair = () => { clearToken(); setTok(""); setPaired(false); setMsg("unpaired"); };

  return (
    <section className="panel control-panel">
      <h2>Control {paired ? <span className="paired-dot">● paired</span> : <span className="unpaired-dot">○ not paired</span>}</h2>

      {!paired ? (
        <div className="control-pair">
          <input
            className="docs-input"
            type="password"
            placeholder="paste control token"
            value={token}
            onChange={(e) => setTok(e.target.value)}
          />
          <button className="docs-btn" onClick={pair}>Pair</button>
          {msg && <span className="push-msg">{msg}</span>}
          <label className="control-session-only" title="More secure on a shared or losable device: the token is wiped when you close the app, so a stolen-but-locked phone retains nothing. You re-paste it each launch.">
            <input
              type="checkbox"
              checked={sessionOnly}
              onChange={(e) => setSessionOnly(e.target.checked)}
            />
            Keep token only for this session (re-paste each launch)
          </label>
        </div>
      ) : (
        <>
          <div className="control-actions">
            <button
              className="docs-btn"
              onClick={() => openConfirm({ action: "t1_offload", params: { ngl: 20 }, label: "Offload T1 to CPU (-ngl 20)", danger: "reversible", onDone: refreshAudit })}
            >
              Offload T1
            </button>
            <button
              className="docs-btn ghost"
              onClick={() => openConfirm({ action: "t1_restore", params: {}, label: "Restore T1 to GPU", danger: "reversible", onDone: refreshAudit })}
            >
              Restore T1
            </button>
            <button className="docs-btn ghost" onClick={unpair}>Unpair</button>
          </div>

          <label className="control-session-only" title="Off = the token is kept across launches on this device. On = wiped when you close the app, so a lost phone retains nothing — but you re-paste it every launch.">
            <input
              type="checkbox"
              checked={sessionOnly}
              onChange={(e) => { setSessionOnly(e.target.checked); setPersistence(e.target.checked); }}
            />
            Keep token only for this session (re-paste each launch)
          </label>

          <h3 className="qh">Recent control actions</h3>
          {readDenials > 0 && (
            <div className="audit-note t-caption">
              {readDenials} denied read{readDenials === 1 ? "" : "s"} in the log
              (unpaired clients hitting the read-gate) — hidden here so they
              don't bury actual actions.
            </div>
          )}
          {audit.length === 0 ? (
            <div className="q-empty">no actions yet</div>
          ) : (
            <ul className="audit">
              {audit.slice().reverse().map((a, i) => (
                <li key={i} className={`audit-${a.result}`}>
                  <span className="au-action">{a.action}</span>
                  <span className="au-result">{a.dry_run ? "dry-run" : a.result}</span>
                  <span className="au-detail">{a.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <BuildStamp serverBuild={serverBuild} />
    </section>
  );
}
