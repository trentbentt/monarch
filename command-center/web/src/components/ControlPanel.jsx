import { useEffect, useState } from "react";
import { getToken, setToken, clearToken, verifyToken, fetchAudit, isSessionOnly } from "../control.js";

/** Control pairing (token) + substrate actuators + audit trail. */
export default function ControlPanel({ openConfirm }) {
  const [token, setTok] = useState(getToken());
  const [paired, setPaired] = useState(false);
  const [msg, setMsg] = useState("");
  const [audit, setAudit] = useState([]);
  const [sessionOnly, setSessionOnly] = useState(isSessionOnly());

  const refreshAudit = () => fetchAudit(15).then((d) => setAudit(d.audit || []));

  useEffect(() => {
    if (getToken()) verifyToken(getToken()).then((ok) => { setPaired(ok); if (ok) refreshAudit(); });
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

          <h3 className="qh">Recent control actions</h3>
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
    </section>
  );
}
