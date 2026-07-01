/**
 * Bespoke Workflows deep-dive. The signature element is the horizontal **stage
 * pipeline**: each workflow is a track of stages reading left→right the way the
 * operator thinks about it (ingest → verify → … → ship). Below each track sits
 * its live freshness and the source/doctrine the scoped supervisor can cite.
 *
 * Data comes from /api/deep/workflows: manifest.items[] (registry: name, what,
 * repo, doctrine, stages) overlaid with detail.items[name] (live freshness).
 */
import { statusClass, ageSeconds, fmtAge } from "../../design/lib.js";

const STATUS_WORD = { ok: "fresh", warn: "stale", crit: "cold", unknown: "quiet" };

function Stage({ stage, idx }) {
  return (
    <li className="wfp-stage">
      <span className="wfp-stage-no t-mono">{String(idx + 1).padStart(2, "0")}</span>
      <span className="wfp-stage-label">{stage.label}</span>
      <span className="wfp-stage-what t-caption">{stage.what}</span>
    </li>
  );
}

function Track({ item, live }) {
  const status = live?.status || "unknown";
  const age = ageSeconds(live?.last_run);
  const reporting = live?.reporting;
  const stages = item.stages || [];

  return (
    <article className={`wf-track ${statusClass(status)}`}>
      <header className="wf-track-head">
        <div className="wf-track-id">
          <span className="wf-track-dot" aria-hidden="true" />
          <h3 className="wf-track-name t-title">{item.name}</h3>
        </div>
        <div className="wf-track-fresh">
          <span className="wf-track-fresh-word eyebrow">{STATUS_WORD[status]}</span>
          <span className="wf-track-fresh-age t-mono">
            {reporting ? (age != null ? `${fmtAge(age)} ago` : "—") : "no report"}
          </span>
        </div>
      </header>

      <p className="wf-track-what">{item.what}</p>

      {stages.length > 0 ? (
        <ol className="wfp-rail" aria-label={`${item.name} stages`}>
          {stages.map((s, i) => <Stage key={s.key} stage={s} idx={i} />)}
        </ol>
      ) : (
        <p className="wf-track-nostages t-caption">Archive — no live stages.</p>
      )}

      <footer className="wf-track-foot">
        {item.repo && <code className="wf-track-repo t-mono">{item.repo}</code>}
        {item.doctrine?.length > 0 && (
          <div className="wf-track-doctrine">
            {item.doctrine.map((d) => <span className="dpv-tag" key={d}>{d}</span>)}
          </div>
        )}
      </footer>
    </article>
  );
}

const RUN_STATUS = { complete: "ok", partial: "warn", running: "warn", failed: "crit" };

function RunsGrounding({ runs, grounding }) {
  const verdicts = Object.entries(grounding?.verdicts || {});
  const totalVerdicts = verdicts.reduce((a, [, n]) => a + n, 0) || 1;
  const rate = grounding?.corrob_rate;
  return (
    <section className="wf-live" aria-label="Runs and grounding">
      <div className="eyebrow wf-live-head">Runs &amp; grounding · live</div>

      {runs?.length > 0 && (
        <div className="wf-runs">
          <div className="wf-runs-timeline" aria-label="Recent runs">
            {runs.slice(0, 14).map((r, i) => (
              <span
                key={`${r.run_date}-${i}`}
                className={`wf-run-tick ${statusClass(RUN_STATUS[(r.status || "").toLowerCase()] || "unknown")}`}
                title={`${r.run_date} · ${r.status} · ${r.articles_used ?? "?"}/${r.articles_fetched ?? "?"} articles`}
              />
            ))}
          </div>
          <div className="wf-runs-latest t-caption">
            latest {runs[0].run_date} · {runs[0].status}
            {runs[0].articles_used != null && ` · ${runs[0].articles_used} articles used`}
            {runs[0].total_tokens != null && ` · ${runs[0].total_tokens.toLocaleString()} tokens`}
          </div>
        </div>
      )}

      {grounding && (grounding.total > 0 || verdicts.length > 0) && (
        <div className="wf-grounding">
          {rate != null && (
            <div className="wf-ground-rate">
              <span className="t-metric-sm">{Math.round(rate * 100)}%</span>
              <span className="t-caption">corroborated · {grounding.total} ledger rows / {grounding.briefs} briefs</span>
            </div>
          )}
          {verdicts.length > 0 && (
            <div className="wf-verdicts" aria-label="Verdict distribution">
              {verdicts.map(([v, n]) => (
                <span
                  key={v}
                  className={`wf-verdict ${v.toLowerCase().includes("refus") || v.toLowerCase().includes("ungrounded") ? "st-crit" : "st-ok"}`}
                  style={{ flex: n / totalVerdicts }}
                  title={`${v}: ${n}`}
                >
                  <span className="wf-verdict-label">{v}</span>
                  <span className="wf-verdict-n t-mono">{n}</span>
                </span>
              ))}
            </div>
          )}
          {grounding.sources?.length > 0 && (
            <ul className="wf-sources">
              {grounding.sources.slice(0, 6).map((s) => (
                <li className="wf-source" key={s.discovered_via}>
                  <span className="wf-source-name t-mono">{s.discovered_via}</span>
                  <span className="wf-source-score t-mono">{s.score.toFixed(2)}</span>
                  <span className="wf-source-sub t-caption">{s.survived}/{s.total}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

export default function WorkflowsDeepDive({ payload }) {
  const manifest = payload?.manifest || {};
  const detail = payload?.detail || {};
  const items = manifest.items || [];
  const liveItems = detail.items || {};
  const facts = detail.facts || [];

  return (
    <div className="wfd">
      {manifest.lede && <p className="dpv-lede">{manifest.lede}</p>}

      {facts.length > 0 && (
        <section className="dpv-facts wfd-facts" aria-label="Live readout">
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

      <section className="wf-tracks" aria-label="Workflows">
        {items.map((it) => (
          <Track key={it.name} item={it} live={liveItems[it.name]} />
        ))}
      </section>

      {(detail.runs?.length > 0 || detail.grounding) ? (
        <RunsGrounding runs={detail.runs} grounding={detail.grounding} />
      ) : (
        <p className="wf-live-empty t-caption">
          No run data yet — workflows report via status.json. Live run history and
          grounding appear here once a workflows DB is configured.
        </p>
      )}

      {(detail.notes || []).length > 0 && (
        <section className="dpv-notes">
          {detail.notes.map((n) => <p className="dpv-note t-caption" key={n}>{n}</p>)}
        </section>
      )}
    </div>
  );
}
