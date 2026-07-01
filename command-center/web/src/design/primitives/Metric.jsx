/**
 * Big mono readout. props: value, unit?, label?, size ('lg'|'sm'), status?
 */
export default function Metric({ value, unit, label, size = "lg", status }) {
  return (
    <div className={`ic-metric ${status ? `st-${status}` : ""}`}>
      <div className={size === "lg" ? "t-metric-lg" : "t-metric-sm"}>
        {value}
        {unit && <span className="ic-metric-unit"> {unit}</span>}
      </div>
      {label && <div className="eyebrow ic-metric-label">{label}</div>}
    </div>
  );
}
