import { useEffect, useRef, useState } from "react";
import { runAction } from "../control.js";
import { canConfirm, isDismissable, nextTabTarget } from "./confirmModal.logic.js";

/** Focusable descendants, in DOM order, for the Tab trap. */
function focusables(root) {
  if (!root) return [];
  return Array.from(
    root.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'
    )
  );
}

/**
 * Two-step safe confirm: on open it runs a DRY-RUN preview (shows exactly what
 * would execute), then the operator confirms to actually run it. Reports the
 * outcome and calls onDone(result) so callers can update optimistically.
 *
 * This is the estate's ONE audited write surface, so it carries the keyboard and
 * focus contract every other surface already had and this one did not:
 *
 * - Escape closes — except mid-flight. Once `running`, the action is already at
 *   the server and dismissing the dialog would hide an outcome the operator must
 *   see, so Escape and the backdrop are both inert until it resolves. Cancelling
 *   the DIALOG was never cancelling the ACTION, and the UI must not imply it is.
 * - role=dialog + aria-modal + aria-labelledby, so the thing that executes
 *   announces itself as a modal rather than as anonymous divs.
 * - A Tab trap, because focus escaping to the page behind an open confirm lets
 *   the operator type into a surface they cannot see.
 * - Focus lands on CANCEL, not Confirm. The safe control takes the default so a
 *   stray Enter closes rather than fires.
 * - Focus returns to whatever opened the dialog on close.
 *
 * `irreversible` additionally requires an explicit acknowledgement (§ below).
 */
export default function ConfirmModal({ action, params, label, danger, onClose, onDone }) {
  const [preview, setPreview] = useState(null);
  const [phase, setPhase] = useState("preview"); // preview | running | done | error
  const [result, setResult] = useState(null);
  // Irreversible actions demand one deliberate extra act. A checkbox, not a
  // second button: a double-click can blow straight through a two-click arm,
  // and cannot blow through a checkbox plus a separate button.
  const [acked, setAcked] = useState(false);

  const dialogRef = useRef(null);
  const cancelRef = useRef(null);
  const openerRef = useRef(null);

  const irreversible = danger === "irreversible";
  // Dismissal is blocked only while the action is in flight.
  const dismissable = isDismissable(phase);

  useEffect(() => {
    let on = true;
    runAction(action, params, { dryRun: true }).then((r) => {
      if (!on) return;
      if (r.ok) setPreview(r.body);
      else setPreview({ error: r.body?.detail || `error ${r.status}` });
    });
    return () => { on = false; };
  }, [action, JSON.stringify(params)]);

  // Remember the opener and restore focus to it on unmount. Without this the
  // operator is dropped at the top of the document after every confirm.
  useEffect(() => {
    openerRef.current = document.activeElement;
    cancelRef.current?.focus();
    return () => {
      const el = openerRef.current;
      if (el && typeof el.focus === "function" && document.contains(el)) el.focus();
    };
  }, []);

  // Escape to dismiss + Tab trapped inside the dialog.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        if (dismissable) { e.stopPropagation(); onClose(); }
        return;
      }
      if (e.key !== "Tab") return;
      const active = document.activeElement;
      const target = nextTabTarget({
        items: focusables(dialogRef.current),
        active,
        shiftKey: e.shiftKey,
        contained: Boolean(dialogRef.current?.contains(active)),
      });
      if (target) {
        e.preventDefault();
        target.focus();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [dismissable, onClose]);

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
  const previewFailed = Boolean(preview?.error);
  // Never runnable on a failed preview; irreversible also needs the acknowledgement.
  const runnable = canConfirm({ preview, irreversible, acked });

  return (
    <div
      className="modal-backdrop"
      onClick={() => { if (dismissable) onClose(); }}
    >
      <div
        className="modal"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="modal-title" id="confirm-modal-title">{label || action}</h3>
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

        {/* The irreversible gate. Shown only while there is still a decision to
            make, and only when the preview actually produced a command — asking
            the operator to acknowledge a command that failed to preview would be
            asking them to acknowledge nothing. */}
        {irreversible && phase === "preview" && !previewFailed && preview != null && (
          <label className="modal-ack">
            <input
              type="checkbox"
              checked={acked}
              onChange={(e) => setAcked(e.target.checked)}
            />
            <span>This cannot be undone. Run it anyway.</span>
          </label>
        )}

        {/* Outcomes are announced: a screen reader must learn the action
            finished without the operator hunting for the line. */}
        <div aria-live="polite">
          {phase === "done" && <div className="modal-ok">✓ {result?.body?.detail || "done"}</div>}
          {phase === "error" && (
            <div className="modal-fail">✗ {result?.body?.detail || `error ${result?.status}`}</div>
          )}
        </div>

        <div className="modal-actions">
          {phase === "preview" && (
            <>
              <button className="docs-btn ghost" ref={cancelRef} onClick={onClose}>Cancel</button>
              <button
                className={`docs-btn ${irreversible ? "btn-danger" : ""}`}
                disabled={!runnable}
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
