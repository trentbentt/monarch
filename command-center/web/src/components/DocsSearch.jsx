import { useState } from "react";

/** "Where's the doc for X" — searches the L6 vault Truth corpus. */
export default function DocsSearch() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async (e) => {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    try {
      const r = await fetch(`/api/docs/search?q=${encodeURIComponent(q)}`);
      setRes(await r.json());
    } catch {
      setRes({ results: [] });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <h2>Docs router</h2>
      <form className="docs-form" onSubmit={run}>
        <input
          className="docs-input"
          placeholder="where's the doc for…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="docs-btn" disabled={busy}>{busy ? "…" : "Find"}</button>
      </form>
      {res && (
        <ul className="docs-results">
          {res.results.length === 0 && <li className="q-empty">no matches</li>}
          {res.results.map((r, i) => (
            <li key={i} className="docs-result">
              <div className="dr-head">
                <span className="dr-file">{r.file}</span>
                <span className="dr-line">:{r.line}</span>
              </div>
              <div className="dr-heading">{r.heading}</div>
              {r.snippet && <div className="dr-snip">{r.snippet}</div>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
