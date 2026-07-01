/**
 * Bespoke Memory deep-dive. The seven-layer architecture as an explorable map:
 * a doctrine-true L1→L7 ladder on the left, and a panel that changes with the
 * selected layer — the L6 vault browser, the L3 semantic search, or a layer
 * read-out (class, locus, live signal, §11 failure mode) for the rest.
 *
 * Data: /api/deep/memory (ladder + facts). The L6/L3 panels fetch their own
 * endpoints (vault tree/note, semantic search) through their components.
 */
import { useState } from "react";
import { statusClass } from "../../design/lib.js";
import VaultBrowser from "./VaultBrowser.jsx";
import SemanticSearch from "./SemanticSearch.jsx";

const CLS_TINT = { Truth: "cls-truth", Index: "cls-index", Memory: "cls-memory" };

export default function MemoryDeepDive({ payload }) {
  const manifest = payload?.manifest || {};
  const detail = payload?.detail || {};
  const caps = manifest.capabilities || {};
  const facts = detail.facts || [];
  const layers = Object.values(detail.items || {}); // ordered L1..L7

  // Default to L6 (the vault — the richest panel) when available, else first layer.
  const [active, setActive] = useState(caps.vault_browser ? "L6" : (layers[0]?.layer || "L1"));
  const [vaultOpenPath, setVaultOpenPath] = useState(null);

  const activeLayer = layers.find((l) => l.layer === active) || layers[0];

  const openInVault = (path) => {
    setActive("L6");
    setVaultOpenPath(path);
  };

  return (
    <div className="mem">
      {manifest.lede && <p className="dpv-lede">{manifest.lede}</p>}

      {facts.length > 0 && (
        <section className="dpv-facts mem-facts" aria-label="Memory readout">
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

      <div className="mem-body">
        {/* Layer ladder */}
        <ol className="mem-ladder" aria-label="Memory layers">
          {layers.map((l) => (
            <li key={l.layer}>
              <button
                className={`mem-rung ${statusClass(l.status)}${active === l.layer ? " is-active" : ""}`}
                onClick={() => setActive(l.layer)}
                aria-pressed={active === l.layer}
              >
                <span className="mem-rung-id t-mono">{l.layer}</span>
                <span className="mem-rung-dot" aria-hidden="true" />
                <span className="mem-rung-name">{l.name}</span>
                <span className={`mem-rung-cls ${CLS_TINT[l.cls] || ""}`}>{l.cls}</span>
                <span className="mem-rung-ms t-mono">
                  {l.response_ms != null ? `${Math.round(l.response_ms)}ms` : (l.reporting ? "—" : "·")}
                </span>
              </button>
            </li>
          ))}
        </ol>

        {/* Active panel */}
        <div className="mem-panel">
          {activeLayer && (
            <header className="mem-panel-head">
              <div className="mem-panel-id">
                <span className="mem-panel-layer t-mono">{activeLayer.layer}</span>
                <h3 className="mem-panel-name t-title">{activeLayer.name}</h3>
                <span className={`mem-rung-cls ${CLS_TINT[activeLayer.cls] || ""}`}>{activeLayer.cls}</span>
              </div>
              <span className="mem-panel-locus t-mono">{activeLayer.locus}</span>
            </header>
          )}

          {active === "L6" && caps.vault_browser ? (
            <VaultBrowser openPath={vaultOpenPath} />
          ) : active === "L3" && caps.semantic_search ? (
            <SemanticSearch onOpenNote={openInVault} />
          ) : (
            <div className="mem-panel-info">
              <p className="mem-panel-what">{activeLayer?.what}</p>
              {active === "L3" && !caps.semantic_search && (
                <p className="dpv-note t-caption">
                  Semantic search is offline — the Loki retrieval layer or embed service isn’t reachable.
                </p>
              )}
              <div className="mem-panel-rows">
                <div className="mem-panel-row">
                  <span className="eyebrow">Live signal</span>
                  <span className="t-mono">
                    {activeLayer?.reporting
                      ? `${activeLayer.status}${activeLayer.response_ms != null ? ` · ${Math.round(activeLayer.response_ms)}ms` : ""}`
                      : "not reporting"}
                  </span>
                </div>
                <div className="mem-panel-row">
                  <span className="eyebrow">Failure mode</span>
                  <span className="t-caption">{activeLayer?.fail}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {(detail.notes || []).length > 0 && (
        <section className="dpv-notes">
          {detail.notes.map((n) => <p className="dpv-note t-caption" key={n}>{n}</p>)}
        </section>
      )}
    </div>
  );
}
