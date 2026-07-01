/**
 * L3 semantic search panel. Runs the operator's query through the Loki retrieval
 * layer (nomic embed → pgvector nearest-neighbor over vault_note_chunks) and shows
 * ranked snippets with a distance bar. "Open in vault" deep-links the hit into the
 * L6 browser. Degrades to a clear note when the embed service or index is down.
 */
import { useState } from "react";
import { apiFetch } from "../../control.js";

function distancePct(d) {
  // <-> L2 distance; smaller is nearer. Map ~[0,1.4] to a filled bar (heuristic,
  // for visual ranking only — the exact number is shown alongside).
  const clamped = Math.max(0, Math.min(1.4, d));
  return Math.round((1 - clamped / 1.4) * 100);
}

export default function SemanticSearch({ onOpenNote }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null); // {results, error, routing}

  async function run() {
    const query = q.trim();
    if (!query || busy) return;
    setBusy(true);
    try {
      const r = await apiFetch("/api/memory/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, k: 8 }),
      });
      setRes(await r.json());
    } catch (e) {
      setRes({ results: [], error: `search failed (${e.message})` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sem">
      <div className="sem-bar">
        <input
          className="sem-input"
          placeholder="Semantic search the vault… (what does the substrate associate with X)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          disabled={busy}
        />
        <button className="sem-go" onClick={run} disabled={busy || !q.trim()}>
          {busy ? "…" : "Search"}
        </button>
      </div>

      {res?.routing?.length > 0 && (
        <div className="sem-routing t-caption">
          this question would also touch {res.routing.filter((l) => l !== "L3").join(", ") || "L3 only"}
        </div>
      )}

      {res?.error && <div className="sem-err dpv-note t-caption">{res.error}</div>}

      {res && !res.error && res.results.length === 0 && (
        <div className="t-caption dd-empty">No matches.</div>
      )}

      <ul className="sem-results">
        {(res?.results || []).map((s, i) => (
          <li className="sem-hit" key={`${s.locator}-${i}`}>
            <div className="sem-hit-head">
              <span className="sem-hit-loc t-mono">{s.locator}</span>
              <span className="sem-hit-dist t-mono">dist {s.score.toFixed(2)}</span>
            </div>
            <div className="sem-hit-bar" aria-hidden="true">
              <span className="sem-hit-bar-fill" style={{ width: `${distancePct(s.score)}%` }} />
            </div>
            <p className="sem-hit-text">{s.text.length > 320 ? s.text.slice(0, 320) + "…" : s.text}</p>
            {s.source && onOpenNote && (
              <button className="sem-hit-open" onClick={() => onOpenNote(s.source)}>
                open in vault →
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
