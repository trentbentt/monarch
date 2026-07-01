import { useState, useRef, useEffect } from "react";
import { apiFetch } from "../control.js";

/**
 * T1 Supervisor console. A conversational turn with the Loki supervisor layer
 * (read-and-propose) over POST /api/supervisor/ask. The supervisor reads live
 * state + ledger + doctrine and answers in natural language; "deep" runs its
 * agentic investigation loop (slower, more grounded).
 *
 * Read-only by contract: the supervisor answers here, it does not act. The model
 * call can take up to ~60s, so a turn shows a live "thinking" state and the input
 * locks until it resolves. Failures surface as a system line, never a crash.
 */
const SUGGESTIONS = [
  "What needs my attention right now?",
  "Why is the current VRAM pressure where it is?",
  "Walk me through the pending decisions.",
];

let _id = 0;
const nextId = () => ++_id;

/**
 * @param {object}  props
 * @param {object}  props.overview   live overview (drives the status light)
 * @param {boolean} props.collapsed  dashboard rail mode (ignored when docked)
 * @param {fn}      props.onToggle   collapse toggle (dashboard only)
 * @param {string}  props.variant    "dock" → full-height scoped pane, no rail
 * @param {object}  props.scope      {domain, label} → grounds every turn in a section
 * @param {string[]}props.suggestions section-specific seed questions
 */
export default function SupervisorChat({
  overview,
  collapsed = false,
  onToggle,
  variant,
  scope = null,
  suggestions,
}) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [deep, setDeep] = useState(false);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);
  const taRef = useRef(null);

  const docked = variant === "dock";
  const seedQuestions = suggestions && suggestions.length ? suggestions : SUGGESTIONS;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, busy]);

  async function send(text) {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput("");
    const userMsg = { id: nextId(), role: "user", text: q };
    const wasDeep = deep;
    setMessages((m) => [...m, userMsg]);
    setBusy(true);
    try {
      const body = { question: q, deep: wasDeep };
      if (scope?.domain) body.scope = { domain: scope.domain };
      const r = await apiFetch("/api/supervisor/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      const answer = data.answer || data.detail || "[no answer returned]";
      setMessages((m) => [
        ...m,
        { id: nextId(), role: "supervisor", text: answer, deep: wasDeep, model: data.model, error: data.error },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { id: nextId(), role: "system", text: `Couldn't reach the supervisor (${e.message}). The backend may be down.` },
      ]);
    } finally {
      setBusy(false);
      taRef.current?.focus();
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  const overall = overview?.overall || "unknown";

  // Collapsed: a slim spine that gives the dashboard its space back. One tap (or
  // pressing a suggestion) opens the full console. Never collapses when docked
  // into a deep-dive — there it is the co-pilot and stays open.
  if (collapsed && !docked) {
    return (
      <button
        className={`sup-rail st-${overall}`}
        onClick={onToggle}
        aria-label="Open supervisor console"
        title="Open supervisor console (T1)"
      >
        <span className="sup-rail-icon" aria-hidden="true">◧</span>
        <span className="sup-rail-label">SUPERVISOR · T1</span>
        {messages.length > 0 && <span className="sup-rail-count t-mono">{messages.length}</span>}
        <span className="sup-rail-dot" aria-hidden="true" />
      </button>
    );
  }

  return (
    <section className={`sup${docked ? " sup-dock" : ""}`} aria-label="Supervisor console">
      <header className="sup-head">
        <div className="sup-head-l">
          <div className="eyebrow">{scope?.label ? `Supervisor · ${scope.label}` : "Supervisor · T1"}</div>
          <div className="t-title sup-title">{scope ? "Dive into the weeds" : "Ask the substrate"}</div>
        </div>
        <div className="sup-head-r">
          <span className={`sup-status st-${overall}`} title="read-and-propose layer">
            <span className="sup-status-dot" aria-hidden="true" />
            read-only
          </span>
          {onToggle && !docked && (
            <button className="sup-collapse" onClick={onToggle} aria-label="Collapse supervisor console" title="Collapse">
              ⤢
            </button>
          )}
        </div>
      </header>

      <div className="sup-thread" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="sup-empty">
            <p className="sup-empty-lede">
              {scope?.label
                ? `Scoped to ${scope.label}. It reads this section’s live state plus the code and doctrine behind it — ask in the weeds, and it cites real source.`
                : "A read-only conversational layer over the daemon. It reads live state, the decision ledger, and doctrine — then answers in plain language."}
            </p>
            <div className="eyebrow sup-empty-head">Try</div>
            <ul className="sup-suggest">
              {seedQuestions.map((s) => (
                <li key={s}>
                  <button className="sup-suggest-btn" onClick={() => send(s)} disabled={busy}>
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`sup-msg sup-${m.role}${m.error ? " sup-msg-err" : ""}`}>
            <div className="sup-msg-who eyebrow">
              {m.role === "user" ? "you" : m.role === "system" ? "system" : "supervisor"}
              {m.role === "supervisor" && m.deep && <span className="sup-tag">deep</span>}
            </div>
            <div className="sup-msg-body">{m.text}</div>
          </div>
        ))}

        {busy && (
          <div className="sup-msg sup-supervisor sup-thinking">
            <div className="sup-msg-who eyebrow">supervisor</div>
            <div className="sup-msg-body sup-dots" aria-label="thinking">
              <span /><span /><span />
              <em>{deep ? "investigating…" : "reading state…"}</em>
            </div>
          </div>
        )}
      </div>

      <div className="sup-compose">
        <textarea
          ref={taRef}
          className="sup-input"
          rows={2}
          placeholder="Ask T1…  (Enter to send · Shift+Enter for newline)"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="sup-compose-row">
          <label className={`sup-deep${deep ? " on" : ""}`}>
            <input
              type="checkbox"
              checked={deep}
              onChange={(e) => setDeep(e.target.checked)}
            />
            <span className="sup-deep-box" aria-hidden="true" />
            deep investigate
          </label>
          <button className="sup-send" onClick={() => send()} disabled={busy || !input.trim()}>
            {busy ? "…" : "Send"}
          </button>
        </div>
      </div>
    </section>
  );
}
