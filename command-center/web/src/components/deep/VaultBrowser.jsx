/**
 * L6 vault browser — a collapsible tree of the Truth corpus, with in-pane reading
 * of a note (read-only). Tree comes from /api/memory/vault/tree; note content from
 * /api/memory/vault/note. An external `openPath` (e.g. from a semantic-search hit)
 * jumps straight to that note.
 */
import { useState, useEffect, useCallback } from "react";
import MarkdownLite from "./MarkdownLite.jsx";
import { apiFetch } from "../../control.js";

function TreeNode({ node, depth, onOpen, activePath }) {
  const [open, setOpen] = useState(depth < 1); // top level expanded
  if (node.kind === "note") {
    return (
      <button
        className={`vb-note${activePath === node.path ? " is-active" : ""}`}
        style={{ paddingLeft: depth * 12 + 8 }}
        onClick={() => onOpen(node.path)}
        title={node.path}
      >
        <span className="vb-note-icon" aria-hidden="true">◦</span>
        {node.name}
      </button>
    );
  }
  return (
    <div className="vb-dir">
      <button
        className="vb-dir-head"
        style={{ paddingLeft: depth * 12 + 4 }}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="vb-dir-caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
        {node.name}
      </button>
      {open && (node.children || []).map((c) => (
        <TreeNode key={c.path || c.name} node={c} depth={depth + 1} onOpen={onOpen} activePath={activePath} />
      ))}
    </div>
  );
}

export default function VaultBrowser({ openPath }) {
  const [tree, setTree] = useState(null);
  const [treeErr, setTreeErr] = useState(false);
  const [active, setActive] = useState(null);
  const [note, setNote] = useState(null);
  const [noteState, setNoteState] = useState("idle"); // idle | loading | error

  useEffect(() => {
    apiFetch("/api/memory/vault/tree")
      .then((r) => r.json())
      .then(setTree)
      .catch(() => setTreeErr(true));
  }, []);

  const open = useCallback(async (path) => {
    setActive(path);
    setNoteState("loading");
    try {
      const r = await apiFetch(`/api/memory/vault/note?path=${encodeURIComponent(path)}`);
      if (!r.ok) throw new Error();
      setNote(await r.json());
      setNoteState("idle");
    } catch {
      setNoteState("error");
    }
  }, []);

  // Jump to a note requested from outside (semantic-search "open in vault").
  useEffect(() => {
    if (openPath) open(openPath);
  }, [openPath, open]);

  return (
    <div className="vault-browser">
      <nav className="vb-tree" aria-label="Vault notes">
        {treeErr && <div className="t-caption dd-empty">Vault tree unavailable.</div>}
        {tree && (tree.children || []).map((c) => (
          <TreeNode key={c.path || c.name} node={c} depth={0} onOpen={open} activePath={active} />
        ))}
      </nav>

      <article className="vb-reader">
        {!active && noteState === "idle" && (
          <div className="vb-reader-empty t-caption">Select a note to read it here.</div>
        )}
        {noteState === "loading" && <div className="t-caption">Reading note…</div>}
        {noteState === "error" && <div className="t-caption dd-empty">Couldn’t read that note.</div>}
        {noteState === "idle" && note && (
          <>
            <div className="vb-reader-path t-mono">{note.path}</div>
            {note.note && <div className="t-caption dpv-note">{note.note}</div>}
            <MarkdownLite text={note.markdown} />
          </>
        )}
      </article>
    </div>
  );
}
