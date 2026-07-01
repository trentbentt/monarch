import { Card } from "../design/primitives";

/** Generic domain tile for domains without a bespoke instrument (routing,
 *  authority, docs). Uses the shared glass Card frame so it sits flush in the
 *  bento beside the rich cards, surfacing the one-line summary and badge counts. */
export default function DomainCard({ domain }) {
  const counts = domain.counts || {};
  const badges = Object.entries(counts).filter(
    ([, v]) => typeof v === "number" || typeof v === "string"
  );
  return (
    <Card eyebrow={domain.label} title={domain.summary} status={domain.status}>
      {badges.length > 0 && (
        <div className="card-badges">
          {badges.slice(0, 6).map(([k, v]) => (
            <span className="badge" key={k}>
              <span className="badge-k">{k.replace(/_/g, " ")}</span>
              <span className="badge-v t-mono">{String(v)}</span>
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}
