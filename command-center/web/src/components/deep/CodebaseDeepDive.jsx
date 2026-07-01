/**
 * Bespoke Codebase deep-dive — a frontend over the L5 structural index. Pick a
 * repo, search its structure, and read where matches concentrate; the docked
 * supervisor (scoped to "codebase") explains any file you land on and cites it.
 *
 * Data: /api/deep/codebase (repo strip + facts) and /api/codebase/search
 * (file/line hits + directory histogram) for the active repo.
 */
import { useState } from "react";
import { statusClass } from "../../design/lib.js";
import { apiFetch } from "../../control.js";

function DirHistogram({ directories }) {
  const entries = Object.entries(directories || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map(([, n]) => n));
  return (
    <div className="cb-hist" aria-label="Match distribution by directory">
      <div className="eyebrow cb-hist-head">Where matches concentrate</div>
      {entries.map(([dir, n]) => (
        <div className="cb-hist-row" key={dir}>
          <span className="cb-hist-dir t-mono">{dir}</span>
          <span className="cb-hist-bar"><span className="cb-hist-fill" style={{ width: `${(n / max) * 100}%` }} /></span>
          <span className="cb-hist-n t-mono">{n}</span>
        </div>
      ))}
    </div>
  );
}

export default function CodebaseDeepDive({ payload }) {
  const manifest = payload?.manifest || {};
  const detail = payload?.detail || {};
  const facts = detail.facts || [];
  const repos = Object.values(detail.items || {}); // {name, raw_name, nodes, edges, role, status}

  const [active, setActive] = useState(repos[0]?.raw_name || null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);

  const activeRepo = repos.find((r) => r.raw_name === active);

  async function run() {
    const query = q.trim();
    if (!query || !active || busy) return;
    setBusy(true);
    try {
      const r = await apiFetch(`/api/codebase/search?project=${encodeURIComponent(active)}&q=${encodeURIComponent(query)}`);
      setRes(await r.json());
    } catch (e) {
      setRes({ results: [], directories: {}, error: `search failed (${e.message})` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cb">
      {manifest.lede && <p className="dpv-lede">{manifest.lede}</p>}

      {facts.length > 0 && (
        <section className="dpv-facts cb-facts" aria-label="Index readout">
          {facts.map((f) => (
            <div className={`dpv-fact ${statusClass(f.status)}`} key={f.label}>
              <span className="dpv-fact-dot" aria-hidden="true" />
              <span className="dpv-fact-label eyebrow">{f.label}</span>
              <span className="dpv-fact-value t-metric-sm">{f.value}</span>
              {f.sub && <span className="dpv-fact-sub t-caption">{f.sub}</span>}
            </div>
          ))}
        </section>
      )}

      {/* Repo strip */}
      <section className="cb-repos" aria-label="Indexed repositories">
        {repos.map((r) => (
          <button
            key={r.raw_name}
            className={`cb-repo${active === r.raw_name ? " is-active" : ""}`}
            onClick={() => { setActive(r.raw_name); setRes(null); }}
            aria-pressed={active === r.raw_name}
          >
            <span className="cb-repo-name">{r.name}</span>
            <span className="cb-repo-counts t-mono">{r.nodes.toLocaleString()} nodes · {r.edges.toLocaleString()} edges</span>
          </button>
        ))}
        {repos.length === 0 && (
          <div className="t-caption dd-empty">
            Structural index unavailable — codebase-memory isn’t reporting.
          </div>
        )}
      </section>

      {activeRepo && (
        <>
          {activeRepo.role && <p className="cb-role t-caption">{activeRepo.role}</p>}
          <div className="cb-searchbar">
            <input
              className="cb-input"
              placeholder={`Search ${activeRepo.name} structure… (symbol, function, pattern)`}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
              disabled={busy}
            />
            <button className="cb-go" onClick={run} disabled={busy || !q.trim()}>
              {busy ? "…" : "Search"}
            </button>
          </div>

          {res?.error && <div className="dpv-note t-caption">{res.error}{res.hint ? ` — ${res.hint}` : ""}</div>}

          {res && !res.error && (
            <div className="cb-results-wrap">
              <DirHistogram directories={res.directories} />
              <div className="cb-results-head t-caption">
                {res.total} match{res.total === 1 ? "" : "es"}{res.total > res.results.length ? ` · showing ${res.results.length}` : ""}
              </div>
              <ul className="cb-results">
                {res.results.map((h, i) => (
                  <li className="cb-hit" key={`${h.file}-${h.line}-${i}`}>
                    <span className="cb-hit-loc t-mono">{h.file}:{h.line ?? "?"}</span>
                    {h.qualified_name && <span className="cb-hit-qn t-mono">{h.qualified_name}</span>}
                    {h.content && <code className="cb-hit-code">{h.content}</code>}
                  </li>
                ))}
                {res.results.length === 0 && <li className="t-caption dd-empty">No structural matches.</li>}
              </ul>
            </div>
          )}
        </>
      )}

      {(detail.notes || []).length > 0 && (
        <section className="dpv-notes">
          {detail.notes.map((n) => <p className="dpv-note t-caption" key={n}>{n}</p>)}
        </section>
      )}
    </div>
  );
}
