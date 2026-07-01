"""
Supervisor retrieval — the read-only path from the operator's question into the
monarch memory architecture (MEMORY_ARCHITECTURE §3.2 Index / §5 routing).

Read-only by construction, exactly like context.py: this module imports no writer
thread, no gate mutator, and no memory-layer *authoring* surface. It only ever
SELECTs (L3), opens SQLite `mode=ro&immutable=1` (L4), runs a read CLI (L5), GETs
(L7), or reads doctrine files (L6). Loki is the Arbiter — it reads the layers,
it does not own their content (memory-arch §3.4).

Each retrieval function is a discrete, independently-testable unit returning
provenance-tagged Snippets — the same units Phase B will expose to the model as
tools. Phase A calls them deterministically: route_layers() picks the layers via
the §8.6 verb heuristic (no model call), the orchestrator fans out under a token
budget, and the result is injected into the grounded context block with its
locators so every retrieved claim remains citable to disk.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

# The declared public surface of this module. command-center's retrieval_bridge
# and loki's own supervisor.context consume THESE names; anything else is
# internal. Keeps the cross-repo seam an explicit contract, not "whatever each
# caller happened to import" (review A3). The Snippet field names are pinned by a
# conformance test so a rename fails loudly instead of silently defaulting.
__all__ = [
    "Snippet",
    "gather",
    "route_layers",
    "search_vault",
    "session_recall",
    "doctrine_section",
    "doctrine_search",
    "code_structure",
    "temporal_recall",
    "format_snippet",
    "format_snippets",
]


@dataclass(frozen=True)
class Snippet:
    """A provenance-tagged unit of retrieved context. `locator` is what the model
    cites so every retrieved claim stays traceable to disk (lower `score` = nearer
    for distance-ranked layers)."""
    layer: str        # "L3" | "L4" | "L5" | "L6" | "L7"
    source: str       # file path / session id / project — the origin artifact
    locator: str      # human-citable address, e.g. "final_memory_architecture.md §7.7"
    score: float      # distance/rank (lower = better) or 0.0 when not ranked
    text: str


# Only the L3 pgvector layer carries a meaningful distance today; the others set
# score=0.0 to mean "not ranked". So the distance tag is shown by LAYER, not by a
# truthy-score test — a perfect L3 hit has distance 0.0 and must still be tagged
# (a falsy-zero check would have hidden the strongest possible match). One shared
# formatter so Phase-A (context._retrieved_block) and Phase-B (agent._run_tool)
# render the [locator] citation the system prompt depends on identically.
_RANKED_LAYERS = {"L3"}


def format_snippet(s: "Snippet") -> str:
    rank = f" (dist {s.score:.2f})" if s.layer in _RANKED_LAYERS else ""
    return f"[{s.layer} {s.locator}]{rank}\n{s.text}"


def format_snippets(snips) -> str:
    return "\n\n".join(format_snippet(s) for s in snips)


# ── L3 pgvector (semantic over the embedded vault) ──────────────────────────────
# Mirrors monarch-stack/seed_vault_embeddings.py + listeners/memory.py exactly.
_EMBED_URL = "http://127.0.0.1:8087/v1/embeddings"
_EMBED_MODEL = "nomic-embed-text-v1.5"
_PG_HOST = os.environ.get("LOKI_PG_HOST", "127.0.0.1")
_PG_PORT = int(os.environ.get("LOKI_PG_PORT", "5433"))
_PG_DB   = os.environ.get("LOKI_PG_DB", "vault")
_PG_USER = os.environ.get("LOKI_PG_USER", "monarch")
_MONARCH_ENV = os.path.expanduser("~/monarch-stack/.env")
_DEFAULT_K = 5

# ── §8.6 verb heuristic → retrieval layer ───────────────────────────────────────
# Word-boundary patterns (not substrings) so "recall" never trips "call" and
# "candidate" never trips "did".
_L5_CODE = re.compile(
    r"\bwho calls\b|\bcalls?\b|\bcallers?\b|\bimports?\b|\bdepends?\b|\bdependenc"
    r"|\brefactor|\bfunction\b|\bsymbol\b|\bcall graph\b|\bimpact of (changing|renam)",
    re.I,
)
_L4_RECALL = re.compile(
    r"\bdid\b|\bdecid|\bdiscuss|\blast (session|time|week|night|conversation)\b"
    r"|\bpast\b|\bremember\b|\bearlier\b|\bpreviously\b",
    re.I,
)
_L7_TRAJECTORY = re.compile(
    r"\bevolv|\bover (the )?(last|past) \w+|\btrajectory\b|\bhistory\b|\btrend"
    r"|\bhow did we get\b|\bover months\b|\bover time\b",
    re.I,
)
# Architecture / meta intent → pull the authoritative L6 doctrine SECTION. Frame-
# gated, NOT a bare layer/tier token: "is T1 up?" is an operational status question
# (answered from state.json) and must NOT drag in doctrine, but "what backs L3" /
# "how is L4 implemented" must. So fire on a wiring/definition FRAME, not on "T1"
# alone. ("runs" is matched only as "what runs"/"runs on" so the trust-ladder sense
# in "how many clean runs" never trips it.)
_L6_ARCH = re.compile(
    r"\bbacked by\b|\bbacks\b|\bbackend\b|\bbased on\b|\bpowered by\b"
    r"|\bwhat (runs|powers|backs|drives)\b|\bruns? on\b"
    r"|\bengine\b|\bdatastore\b|\bunderl(ying|ies)\b"
    r"|\bimplemented?\b|\bwired\b|\barchitecture\b"
    r"|\bwhat (is|are)\b[^?]*\b(L[1-7]|T[1-5])\b"
    r"|\bhow (is|are|does)\b[^?]*\b(work|wired|implemented|built|set up|configured)\b",
    re.I,
)


def route_layers(question: str) -> List[str]:
    """Deterministically select which memory layers to retrieve from, per the
    §8.6 verb heuristic. L3 (vault semantic) is the default floor and a near-
    universal complement, so it is always included. Never returns empty."""
    q = question or ""
    layers: List[str] = []
    if _L5_CODE.search(q):
        layers.append("L5")
    if _L4_RECALL.search(q):
        layers.append("L4")
    if _L7_TRAJECTORY.search(q):
        layers.append("L7")
    if _L6_ARCH.search(q):
        layers.append("L6")          # architecture/meta → authoritative doctrine §
    if "L3" not in layers:
        layers.append("L3")          # vault semantic — the floor
    return layers


def _embed_post(url: str, payload: dict) -> dict:
    """HTTP POST to the local embed service. Isolated so tests stub the network
    at one seam."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


@lru_cache(maxsize=64)
def _embed_query(text: str) -> List[float]:
    """Embed an operator QUERY. nomic-embed-text-v1.5 is asymmetric: queries use
    the `search_query:` prefix (the seed indexes documents with `search_document:`),
    so this prefix is load-bearing for recall quality. A query's embedding is a pure
    function of its text, so it is memoized — a --deep loop that re-issues the same
    vault query pays one embed round-trip, not N."""
    body = _embed_post(_EMBED_URL, {"model": _EMBED_MODEL,
                                    "input": f"search_query: {text}"})
    return body["data"][0]["embedding"]


@lru_cache(maxsize=1)
def _pg_password() -> Optional[str]:
    """Read MONARCH_POSTGRES_PASSWORD from ~/monarch-stack/.env once per process
    rather than re-reading + re-parsing the file on every connection."""
    try:
        text = Path(_MONARCH_ENV).read_text()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    m = re.search(r"^MONARCH_POSTGRES_PASSWORD=(.*)$", text, re.M)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'")


def _pg_connect():
    """Read-only-by-use psycopg2 connection to monarch-postgres/vault. Lazy import
    so the module loads without psycopg2 and unit tests can stub this seam."""
    import psycopg2  # lazy: not needed when _pg_connect is stubbed
    return psycopg2.connect(host=_PG_HOST, port=_PG_PORT, dbname=_PG_DB,
                            user=_PG_USER, password=_pg_password(), connect_timeout=3)


def search_vault(query: str, k: int = _DEFAULT_K) -> List[Snippet]:
    """L3 — semantic search over `vault_note_chunks`. SELECT-only; nearest-first.
    Raises on backend failure (the orchestrator catches and marks degradation)."""
    vec = _embed_query(query)
    # A non-finite component (nan/inf) would serialize to 'nan'/'inf' and make
    # postgres reject the ::vector literal with an opaque syntax error mid-query.
    # Fail early with a clear cause so gather() degrades L3 cleanly instead.
    if not all(math.isfinite(x) for x in vec):
        raise ValueError("embedding contains a non-finite component")
    vec_lit = "[" + ",".join(repr(float(x)) for x in vec) + "]"
    conn = _pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT path, chunk_idx, content, embedding <-> %s::vector AS dist "
            "FROM vault_note_chunks ORDER BY embedding <-> %s::vector LIMIT %s",
            (vec_lit, vec_lit, k),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out: List[Snippet] = []
    for path, chunk_idx, content, dist in rows:
        out.append(Snippet(
            layer="L3", source=path,
            locator=f"{path} §chunk {chunk_idx}",
            score=float(dist), text=content,
        ))
    return out


# ── L4 Hermes session search (FTS5 keyword, read-only) ──────────────────────────
_HERMES_STATE_DB = os.path.expanduser("~/.hermes/state.db")


def _fts_match_query(query: str) -> str:
    """Turn a free-text question into an FTS5 OR-of-terms match (the buildFtsQuery
    pattern recorded as the monarch FTS standard, memory-arch §14). Quote each
    alnum token so punctuation in the question can't become FTS operators.

    Keep tokens of length >= 2: this stack's load-bearing vocabulary is two-char
    tokens (T1, T2, T4, L3, L4, L5, L7). The old `> 2` filter dropped every one of
    them, so a query like "is T1 up?" tokenized to nothing and L4 silently returned
    no hits — reported to the model as "found nothing" rather than "unsearchable",
    inviting confabulation-by-omission about the exact terms this stack runs on."""
    terms = [f'"{t}"' for t in re.findall(r"\w+", query) if len(t) >= 2]
    return " OR ".join(terms)


def session_recall(query: str, k: int = _DEFAULT_K) -> List[Snippet]:
    """L4 — keyword search over Hermes conversation history. Opens state.db
    READ-ONLY (`mode=ro&immutable=1`) so it never locks or mutates a live session
    and needs no Hermes gateway. Raises if the DB is absent/locked (orchestrator
    catches and marks degradation)."""
    import sqlite3  # stdlib; lazy for symmetry with the other backends
    match = _fts_match_query(query)
    if not match:
        return []
    uri = f"file:{_HERMES_STATE_DB}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        cur = conn.execute(
            "SELECT m.session_id, m.role, m.content "
            "FROM messages_fts f JOIN messages m ON m.id = f.rowid "
            "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, k),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out: List[Snippet] = []
    for session_id, role, content in rows:
        out.append(Snippet(
            layer="L4", source=session_id,
            locator=f"session {str(session_id)[:8]} ({role})",
            score=0.0, text=content or "",
        ))
    return out


# ── L6 doctrine sections (section-addressed; replaces the head-excerpt) ──────────
_DOCTRINE_FILES = {
    "system": Path.home() / "vault/final_master_summary.md",
    "memory": Path.home() / "vault/final_memory_architecture.md",
    "handoff": Path.home() / "vault/final_handoff.md",
}

_HEADING_RE = re.compile(r"^(#+)\s+(.*)$")


def _extract_section(lines: List[str], start: int, depth: int) -> str:
    """The heading at lines[start] (depth = number of leading '#') down to the next
    same-or-higher heading, joined and stripped. One bounding implementation shared
    by doctrine_section (number-addressed) and doctrine_search (name-addressed)."""
    body = [lines[start]]
    for ln in lines[start + 1:]:
        h = re.match(r"^(#+)\s", ln)
        if h and len(h.group(1)) <= depth:
            break
        body.append(ln)
    return "\n".join(body).strip()


def doctrine_section(file_key: str, section: str) -> Optional[Snippet]:
    """L6 — return exactly the requested doctrine section (e.g. '§7.7'), bounded to
    the next same-or-higher heading. None if the file or section is absent. This is
    the cure for the 4 KB head-excerpt: the model gets the section that answers the
    question, not the document preamble."""
    # An empty section is NOT a request for the whole file: `re.escape("") + "(?![\\w.])"`
    # is a bare zero-width lookahead that matches at column 0 of every heading, which
    # would silently return the file's FIRST section (the preamble) — reintroducing the
    # exact 4 KB head-excerpt confabulation this function exists to kill. Refuse it.
    if not section or not section.strip():
        return None
    path = _DOCTRINE_FILES.get(file_key)
    if path is None or not Path(path).exists():
        return None
    lines = Path(path).read_text(errors="replace").splitlines()
    # Match the section as a whole token, not a substring: a bare "§7" must NOT
    # match heading "§7.7", and "§7.7" must NOT match "§7.70" — the negative
    # lookahead forbids a trailing digit or dot right after the requested section.
    sec_re = re.compile(re.escape(section) + r"(?![\w.])")
    for i, ln in enumerate(lines):
        h = re.match(r"^(#+)\s", ln)
        if h and sec_re.search(ln):
            return Snippet(
                layer="L6", source=str(path),
                locator=f"{path.name} {section}", score=0.0,
                text=_extract_section(lines, i, len(h.group(1))),
            )
    return None


def doctrine_search(query: str, k: int = _DEFAULT_K) -> List[Snippet]:
    """L6 — find the doctrine SECTION whose heading best matches the question's
    terms BY NAME (operators say 'L3', not '§7.3'). Returns bounded sections,
    best-heading-match first. Pure file reads; a missing/unreadable file is skipped;
    never raises into gather(). This is the name→section path the number-addressed
    doctrine_section lacks — the cure for an architecture question retrieving fuzzy
    vault chunks instead of the canonical §-section that answers it."""
    tokens = {t.lower() for t in re.findall(r"\w+", query) if len(t) >= 2}
    if not tokens:
        return []
    scored = []                          # (-score, file_order, heading_line, Snippet)
    for forder, (key, path) in enumerate(_DOCTRINE_FILES.items()):
        try:
            if not Path(path).exists():
                continue
            lines = Path(path).read_text(errors="replace").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines):
            h = _HEADING_RE.match(ln)
            if not h:
                continue
            heading = h.group(2).lower()
            score = sum(1 for t in tokens
                        if re.search(r"\b" + re.escape(t) + r"\b", heading))
            if score == 0:
                continue
            scored.append((-score, forder, i, Snippet(
                layer="L6", source=str(path),
                locator=f"{path.name} {h.group(2).strip()}", score=0.0,
                text=_extract_section(lines, i, len(h.group(1))),
            )))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [snip for *_, snip in scored][:k]


# ── L5 codebase-memory (structural code search) ─────────────────────────────────
_L5_BIN = os.path.expanduser("~/.local/bin/codebase-memory-mcp")
_L5_PROJECT = os.environ.get("LOKI_SUPERVISOR_L5_PROJECT", "home-operator-projects-loki")


def _l5_cli(pattern: str, project: str) -> List[dict]:
    """Run codebase-memory `search_code` and return the raw results list. Isolated
    so tests stub the subprocess. Raises on non-zero exit / unparsable output."""
    proc = subprocess.run(
        [_L5_BIN, "cli", "--json", "search_code",
         json.dumps({"pattern": pattern, "project": project})],
        capture_output=True, text=True, timeout=15,
    )
    outer = json.loads(proc.stdout)                       # {"content":[{"text": "<json>"}]}
    inner = json.loads(outer["content"][0]["text"])
    return inner.get("results", [])


def code_structure(query: str, k: int = _DEFAULT_K) -> List[Snippet]:
    """L5 — structural code search (call graph / symbols) over the indexed repos.
    Raises on backend failure (orchestrator catches)."""
    out: List[Snippet] = []
    for r in _l5_cli(query, _L5_PROJECT)[:k]:
        qn = r.get("qualified_name", r.get("node", "?"))
        out.append(Snippet(
            layer="L5", source=r.get("file", "?"),
            locator=f"{r.get('file','?')}:{r.get('start_line','?')} {qn}",
            score=0.0,
            text=f"{r.get('label','')} {qn} "
                 f"(lines {r.get('start_line','?')}-{r.get('end_line','?')})".strip(),
        ))
    return out


# ── L7 EverCore (long-horizon temporal) ─────────────────────────────────────────
_EVERCORE_SEARCH_URL = "http://127.0.0.1:1995/api/v1/memories/search"
_L7_USER = os.environ.get("LOKI_SUPERVISOR_L7_USER", "monarch")


def _l7_search(query: str, k: int) -> dict:
    """POST to EverCore search; return the `data` payload. Isolated for tests."""
    req = urllib.request.Request(
        _EVERCORE_SEARCH_URL,
        data=json.dumps({"query": query, "filters": {"user_id": _L7_USER},
                         "top_k": k}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read()).get("data", {})


def temporal_recall(query: str, k: int = _DEFAULT_K) -> List[Snippet]:
    """L7 — long-horizon temporal recall (episodes / trajectory). Raises on backend
    failure (orchestrator catches)."""
    data = _l7_search(query, k)
    out: List[Snippet] = []
    for ep in (data.get("episodes") or []) + (data.get("raw_messages") or []):
        text = ep.get("content") or ep.get("text") or json.dumps(ep)[:300]
        out.append(Snippet(
            layer="L7", source="evercore",
            locator=f"episode {ep.get('id', '?')}", score=0.0, text=text,
        ))
    return out[:k]


# ── Orchestrator: route → fan out → degrade → budget → explicit §sections ────────
_DEFAULT_CHAR_BUDGET = int(os.environ.get("LOKI_SUPERVISOR_RETRIEVAL_BUDGET", "8000"))
_SECTION_RE = re.compile(r"§\d+(?:\.\d+)*")
# layer → function NAME (resolved through the module namespace at call time, so a
# single backend can be stubbed/patched and degraded independently).
_LAYER_FUNC_NAMES = {
    "L3": "search_vault", "L4": "session_recall",
    "L5": "code_structure", "L7": "temporal_recall",
}


@dataclass
class RetrievalResult:
    """What gather() hands context.py: the ranked snippets that fit the budget, the
    layers consulted, and human-readable degradation/truncation notes (so the model
    is told a layer was down rather than silently missing it)."""
    snippets: List[Snippet]
    notes: List[str]
    layers: List[str]


def gather(question: str, k: int = _DEFAULT_K,
           char_budget: int = _DEFAULT_CHAR_BUDGET) -> RetrievalResult:
    """Deterministically assemble retrieved context for a question. Never raises
    into the caller's turn: every backend is isolated, failures become notes."""
    layers = route_layers(question)
    notes: List[str] = []
    g = globals()

    # Priority tier: explicit "§N.N" references are a high-confidence operator
    # signal — pull those exact L6 sections FIRST so the budget clamp can never
    # evict an explicitly-named section in favor of a fuzzy semantic hit.
    priority: List[Snippet] = []
    doc_fn = g.get("doctrine_section")
    for sec in dict.fromkeys(_SECTION_RE.findall(question)):   # ordered de-dup
        for key in _DOCTRINE_FILES:
            try:
                snip = doc_fn(key, sec)
            except Exception:
                snip = None
            if snip is not None:
                priority.append(snip)

    # Name-addressed doctrine: an architecture question ("what backs L3") names a
    # layer/tier, not a §number. doctrine_search resolves the NAME to the canonical
    # section; it joins the priority tier so the budget can't evict it for a fuzzy
    # hit. Dedup on (source, text) so a section pulled BOTH by number and by name
    # (differing locators, identical body) appears once.
    seen_sections = {(s.source, s.text) for s in priority}
    if "L6" in layers:
        search_fn = g.get("doctrine_search")
        try:
            hits = search_fn(question, k) if search_fn else []
        except Exception as exc:                # graceful degradation, never raise
            hits = []
            notes.append(f"L6 doctrine search unavailable: {type(exc).__name__}")
        for snip in hits:
            if (snip.source, snip.text) not in seen_sections:
                priority.append(snip)
                seen_sections.add((snip.source, snip.text))

    # Routed-layer tier: deterministic §8.6 fan-out, each backend isolated.
    routed: List[Snippet] = []
    for layer in layers:
        if layer == "L6":
            continue                            # served from the priority tier above
        fname = _LAYER_FUNC_NAMES.get(layer)
        fn = g.get(fname) if fname else None
        if fn is None:
            notes.append(f"{layer} not wired in Phase A")
            continue
        try:
            routed.extend(fn(question, k))
        except Exception as exc:               # graceful degradation, never raise
            notes.append(f"{layer} unavailable: {type(exc).__name__}: {str(exc)[:60]}")

    snippets = priority + routed
    # Budget clamp (character proxy for tokens) — keep nearest/first, mark the cut.
    clamped: List[Snippet] = []
    used = 0
    for s in snippets:
        if used + len(s.text) > char_budget:
            notes.append("retrieval truncated to fit budget")
            break
        clamped.append(s)
        used += len(s.text)

    return RetrievalResult(snippets=clamped, notes=notes, layers=layers)
