/**
 * A tiny, dependency-free, safe markdown renderer for vault notes. We control the
 * corpus (L6 Truth docs), but we still render structured React nodes — never
 * dangerouslySetInnerHTML — so there is no HTML-injection surface. Handles the
 * subset vault notes actually use: headings, fenced code, list items, blockquotes,
 * horizontal rules, and inline `code`. Everything else renders as a paragraph.
 */

function inline(text, keyBase) {
  // Split on inline code spans; render those as <code>, the rest as plain text.
  const parts = text.split(/(`[^`]+`)/g);
  return parts.map((p, i) => {
    if (p.startsWith("`") && p.endsWith("`") && p.length > 1) {
      return <code className="md-code-inline" key={`${keyBase}-${i}`}>{p.slice(1, -1)}</code>;
    }
    return <span key={`${keyBase}-${i}`}>{p}</span>;
  });
}

export default function MarkdownLite({ text }) {
  const lines = (text || "").split("\n");
  const out = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.trimStart().startsWith("```")) {
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++; // closing fence
      out.push(<pre className="md-pre" key={key++}><code>{buf.join("\n")}</code></pre>);
      continue;
    }

    // Heading
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      const lvl = h[1].length;
      out.push(
        <div className={`md-h md-h${lvl}`} key={key++}>{inline(h[2], `h${key}`)}</div>
      );
      i++;
      continue;
    }

    // Horizontal rule
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      out.push(<hr className="md-hr" key={key++} />);
      i++;
      continue;
    }

    // Blockquote
    if (line.trimStart().startsWith(">")) {
      out.push(
        <blockquote className="md-quote" key={key++}>
          {inline(line.replace(/^\s*>\s?/, ""), `q${key}`)}
        </blockquote>
      );
      i++;
      continue;
    }

    // List item (- * or 1.)
    const li = line.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
    if (li) {
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(/^\s*([-*]|\d+\.)\s+(.*)$/);
        if (!m) break;
        items.push(<li key={items.length}>{inline(m[2], `li${key}-${items.length}`)}</li>);
        i++;
      }
      out.push(<ul className="md-list" key={key++}>{items}</ul>);
      continue;
    }

    // Blank line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph (gather consecutive non-blank, non-special lines)
    const buf = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^(#{1,6})\s/.test(lines[i]) &&
      !lines[i].trimStart().startsWith("```") &&
      !lines[i].trimStart().startsWith(">") &&
      !/^\s*([-*]|\d+\.)\s+/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    out.push(<p className="md-p" key={key++}>{inline(buf.join(" "), `p${key}`)}</p>);
  }

  return <div className="md">{out}</div>;
}
