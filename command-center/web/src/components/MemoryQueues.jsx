import { useEffect, useState } from "react";

function fmtAge(s) {
  if (s == null) return "age ?";
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

/** Skill-draft + curated-GC queues (read straight from the Hermes stores). */
export default function MemoryQueues() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let on = true;
    const load = () =>
      fetch("/api/memory/queues")
        .then((r) => r.json())
        .then((d) => on && setData(d))
        .catch(() => on && setErr("unreachable"));
    load();
    const id = setInterval(load, 30000);
    return () => {
      on = false;
      clearInterval(id);
    };
  }, []);

  if (err) return null;
  if (!data) return null;
  const sd = data.skill_drafts || {};
  const gc = data.curated_gc || {};

  return (
    <section className="panel">
      <h2>Memory queues</h2>

      <h3 className="qh">Skill drafts {sd.available ? `(${sd.items?.length || 0})` : "—"}</h3>
      {!sd.available ? (
        <div className="q-empty">drafts dir not bootstrapped</div>
      ) : sd.items.length === 0 ? (
        <div className="q-empty">none pending</div>
      ) : (
        <ul className="queue">
          {sd.items.map((it) => (
            <li key={it.name} className={it.stale ? "stale" : ""}>
              <span className="q-name">{it.name}</span>
              <span className="q-age">{fmtAge(it.age_seconds)}{it.stale ? " · STALE" : ""}</span>
              {it.summary && <div className="q-sum">{it.summary}</div>}
            </li>
          ))}
        </ul>
      )}

      <h3 className="qh">Curated-GC proposals {gc.available ? `(${gc.items?.length || 0})` : "—"}</h3>
      {!gc.available ? (
        <div className="q-empty">janitor not yet run</div>
      ) : gc.items.length === 0 ? (
        <div className="q-empty">curated tier clean</div>
      ) : (
        <ul className="queue">
          {gc.items.map((it) => (
            <li key={it.id} className={it.stale ? "stale" : ""}>
              <span className="q-name">{it.id}</span>
              <span className="chip chip-muted">{it.class}/{it.kind}</span>
              <span className="q-age">{fmtAge(it.age_seconds)}{it.stale ? " · STALE" : ""}</span>
              {it.rationale && <div className="q-sum">{it.rationale}</div>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
