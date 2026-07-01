/**
 * The default Overview tab for any domain that has a provider but no bespoke
 * deep-dive yet. Renders the manifest (what this domain is + the source behind
 * it) and the live detail facts. This is what makes *every* card go deep on day
 * one; richer per-domain views (WorkflowsDeepDive, future MemoryDeepDive) replace
 * it where they exist.
 */
import { statusClass } from "../../design/lib.js";

function FactRow({ fact }) {
  return (
    <div className={`dpv-fact ${statusClass(fact.status)}`}>
      <span className="dpv-fact-dot" aria-hidden="true" />
      <span className="dpv-fact-label eyebrow">{fact.label}</span>
      <span className="dpv-fact-value t-metric-sm">{fact.value}</span>
      {fact.sub && <span className="dpv-fact-sub t-caption">{fact.sub}</span>}
    </div>
  );
}

function ItemCard({ name, item, live }) {
  const status = live?.status || "unknown";
  return (
    <article className={`dpv-item ${statusClass(status)}`}>
      <header className="dpv-item-head">
        <span className="dpv-item-dot" aria-hidden="true" />
        <h3 className="dpv-item-name t-title">{name}</h3>
        {live?.last_run && (
          <span className="dpv-item-fresh t-mono" title="last reported run">
            {new Date(live.last_run).toLocaleDateString()}
          </span>
        )}
      </header>
      {item.what && <p className="dpv-item-what">{item.what}</p>}
      <div className="dpv-item-meta">
        {item.repo && <code className="dpv-item-repo t-mono">{item.repo}</code>}
        {item.doctrine?.length > 0 && (
          <div className="dpv-item-doctrine">
            {item.doctrine.map((d) => (
              <span className="dpv-tag" key={d}>{d}</span>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

export default function GenericDeepDive({ payload }) {
  const manifest = payload?.manifest || {};
  const detail = payload?.detail || {};
  const facts = detail.facts || [];
  const items = manifest.items || [];
  const liveItems = detail.items || {};

  return (
    <div className="dpv">
      {manifest.lede && <p className="dpv-lede">{manifest.lede}</p>}

      {facts.length > 0 && (
        <section className="dpv-facts" aria-label="Live readout">
          {facts.map((f) => <FactRow key={f.label} fact={f} />)}
        </section>
      )}

      {items.length > 0 && (
        <section className="dpv-items" aria-label="Sections">
          {items.map((it) => (
            <ItemCard key={it.name} name={it.name} item={it} live={liveItems[it.name]} />
          ))}
        </section>
      )}

      {(detail.notes || []).length > 0 && (
        <section className="dpv-notes">
          {detail.notes.map((n) => (
            <p className="dpv-note t-caption" key={n}>{n}</p>
          ))}
        </section>
      )}
    </div>
  );
}
