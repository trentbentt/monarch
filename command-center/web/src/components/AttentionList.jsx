/** The phone's reason to exist: only the things that are wrong, worst first. */
export default function AttentionList({ attention }) {
  if (!attention || attention.length === 0) {
    return <div className="attention-empty">Nothing needs your attention.</div>;
  }
  return (
    <ul className="attention">
      {attention.map((a, i) => (
        <li key={i} className={`attention-item lvl-${a.status}`}>
          <span className="attention-domain">{a.domain}</span>
          <span className="attention-msg">{a.message}</span>
        </li>
      ))}
    </ul>
  );
}
