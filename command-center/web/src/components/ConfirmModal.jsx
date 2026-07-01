import { useEffect, useState } from "react";
import { runAction } from "../control.js";

/**
 * Two-step safe confirm: on open it runs a DRY-RUN preview (shows exactly what
 * would execute), then the operator confirms to actually run it. Reports the
 * outcome and calls onDone(result) so callers can update optimistically.
 */
export default function ConfirmModal({ action, params, label, danger, onClose, onDone }) {
  const [preview, setPreview] = useState(null);
  const [phase, setPhase] = useState("preview"); // preview | running | done | error
  const [result, setResult] = useState(null);

  useEffect(() => {
    let on = true;
    runAction(action, params, { dryRun: true }).then((r) => {
      if (!on) return;
      if (r.ok) setPreview(r.body);
      else setPreview({ error: r.body?.detail || `error ${r.status}` });
    });
    return () => { on = false; };
  }, [action, JSON.stringify(params)]);

  const confirm = async () => {
    setPhase("running");
    const r = await runAction(action, params, { confirm: true });
    setResult(r);
    if (r.ok) {
      setPhase("done");
      onDone && onDone(r.body);
    } else {
      setPhase("error");
    }
  };

  const wouldRun = preview?.would_run;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title">{label || action}</h3>
        <div className={`modal-danger danger-${danger || "info"}`}>{danger || "info"}</div>

        <div className="modal-preview">
          <div className="mp-label">Will run:</div>
          {preview == null ? (
            <code className="mp-code">previewing…</code>
          ) : preview.error ? (
            <code className="mp-code mp-err">{preview.error}</code>
          ) : (
            <code className="mp-code">
              {Array.isArray(wouldRun) ? wouldRun.join(" ") : String(wouldRun)}
            </code>
          )}
        </div>

        {phase === "done" && <div className="modal-ok">✓ {result?.body?.detail || "done"}</div>}
        {phase === "error" && (
          <div className="modal-fail">✗ {result?.body?.detail || `error ${result?.status}`}</div>
        )}

        <div className="modal-actions">
          {phase === "preview" && (
            <>
              <button className="docs-btn ghost" onClick={onClose}>Cancel</button>
              <button
                className={`docs-btn ${danger === "irreversible" ? "btn-danger" : ""}`}
                disabled={preview?.error}
                onClick={confirm}
              >
                Confirm
              </button>
            </>
          )}
          {(phase === "running") && <button className="docs-btn" disabled>Running…</button>}
          {(phase === "done" || phase === "error") && (
            <button className="docs-btn" onClick={onClose}>Close</button>
          )}
        </div>
      </div>
    </div>
  );
}
