/**
 * The raw substrate slice behind a domain, as a readable key→value tree (not a
 * JSON dump). Extracted from the old in-place DomainDetail so the drill-down peek
 * lives on as the "Raw signal" tab inside the full-page deep-dive.
 */

// Domain → the state.json slice(s) that feed it.
export function sliceFor(key, state) {
  if (!state) return null;
  const comps = state.health?.components || [];
  switch (key) {
    case "vitals": return { resources: state.resources, hardware: state.hardware };
    case "tiers": return { tiers: state.tiers, workloads: state.workloads };
    case "workflows": return { n8n: comps.find((c) => c.name === "n8n") || null, workloads: state.workloads };
    case "routing": return { components: comps.filter((c) => ["litellm", "validation-gate", "lora-dispatcher"].includes(c.name)) };
    case "memory": return state.memory;
    case "events": return { events: state.events };
    case "schedule": return state.schedule;
    case "authority": return state.decisions;
    case "spend": return { quotas: state.quotas, operator: state.operator };
    default: return null;
  }
}

function Val({ v }) {
  if (v == null) return <span className="kv-null">—</span>;
  if (typeof v === "boolean") return <span className={`kv-bool kv-${v}`}>{String(v)}</span>;
  if (typeof v === "number") return <span className="kv-num t-mono">{v}</span>;
  return <span className="kv-str">{String(v)}</span>;
}

function Node({ k, v, depth }) {
  const isObj = v && typeof v === "object";
  if (!isObj) {
    return (
      <div className="kv-row" style={{ paddingLeft: depth * 12 }}>
        <span className="kv-key">{k}</span>
        <Val v={v} />
      </div>
    );
  }
  const entries = Array.isArray(v)
    ? v.map((item, i) => [String(i), item])
    : Object.entries(v);
  return (
    <div className="kv-group">
      <div className="kv-row kv-branch" style={{ paddingLeft: depth * 12 }}>
        <span className="kv-key">{k}</span>
        <span className="kv-count">{Array.isArray(v) ? `[${entries.length}]` : `{${entries.length}}`}</span>
      </div>
      {entries.slice(0, 60).map(([ck, cv]) => (
        <Node key={ck} k={ck} v={cv} depth={depth + 1} />
      ))}
    </div>
  );
}

export default function RawSignal({ domainKey, state, summary }) {
  const slice = sliceFor(domainKey, state);
  return (
    <div className="dd-tree raw-signal">
      {slice
        ? Object.entries(slice).map(([k, v]) => <Node key={k} k={k} v={v} depth={0} />)
        : (
          <div className="t-caption dd-empty">
            No raw state slice for this section{summary ? ` — ${summary}` : ""}.
          </div>
        )}
    </div>
  );
}
