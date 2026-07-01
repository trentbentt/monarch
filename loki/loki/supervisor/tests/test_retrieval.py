"""
Retrieval-layer tests — the supervisor's read-only path into the memory
architecture (L3 pgvector / L4 Hermes FTS5 / L5 codebase-memory / L7 EverCore /
L6 doctrine sections).

Two things matter here and are asserted below:
  1. Retrieval is DETERMINISTIC where it must be (the §8.6 verb router) and
     query-directed where it must be (functions take the operator's question).
  2. Retrieval is READ-ONLY and DEGRADES GRACEFULLY — a down backend yields a
     marker, never an exception into the operator's turn, and never a write.

Run under the monarch venv:
  ~/venv/inference/bin/python3 -m pytest loki/supervisor/tests/test_retrieval.py -q
"""

from __future__ import annotations

import pytest

from loki.supervisor import retrieval as R


# ── §8.6 deterministic verb router ──────────────────────────────────────────────
def test_router_code_structure_question_routes_to_L5():
    assert "L5" in R.route_layers("who calls validate_grounding and what imports it?")


def test_router_recall_question_routes_to_L4():
    assert "L4" in R.route_layers("what did we decide last session about the offload?")


def test_router_trajectory_question_routes_to_L7():
    assert "L7" in R.route_layers("how has the VRAM budget evolved over the last month?")


def test_router_plain_doc_question_defaults_to_L3():
    assert R.route_layers("why do we keep T1 always-on?") == ["L3"]


def test_router_returns_a_list_and_never_empty():
    out = R.route_layers("anything at all")
    assert isinstance(out, list) and out          # default floor is L3


def test_router_architecture_question_routes_to_L6():
    assert "L6" in R.route_layers("what backs L3?")
    assert "L6" in R.route_layers("how is L4 implemented?")
    assert "L6" in R.route_layers("what is T1?")


def test_router_operational_status_question_does_not_route_to_L6():
    # "is T1 up?" is an OPERATIONAL status question answered from state.json — it
    # must NOT pull a doctrine section just because it names a tier (false-fire guard).
    assert "L6" not in R.route_layers("is T1 up?")
    assert "L6" not in R.route_layers("what did we decide last session?")
    assert "L6" not in R.route_layers("who calls classify and what imports it?")
    assert "L6" not in R.route_layers("how many clean runs does offload_t1 have?")


# ── L3 search_vault (semantic over the embedded vault) ──────────────────────────
class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []
    def execute(self, sql, params=None):
        self.executed.append((sql, params))
    def fetchall(self):
        return self._rows
    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows):
        self._cur = _FakeCursor(rows)
    def cursor(self):
        return self._cur
    def close(self):
        pass


def test_search_vault_returns_ranked_provenance_snippets(monkeypatch):
    monkeypatch.setattr(R, "_embed_query", lambda text: [0.1, 0.2, 0.3])
    rows = [
        ("final_memory_architecture.md", 41, "L7 EverMemOS consolidates MemScenes…", 0.12),
        ("final_master_summary.md", 7, "T1 is the Loki reasoning brain…", 0.20),
    ]
    monkeypatch.setattr(R, "_pg_connect", lambda: _FakeConn(rows))

    out = R.search_vault("how does L7 consolidation work?", k=2)

    assert len(out) == 2
    assert all(s.layer == "L3" for s in out)
    assert "final_memory_architecture.md" in out[0].locator
    assert out[0].text.startswith("L7 EverMemOS")
    assert out[0].score == 0.12                       # distance carried as score
    assert out[0].score <= out[1].score               # ranked nearest-first


def test_search_vault_embeds_query_with_search_query_prefix(monkeypatch):
    # nomic-embed is asymmetric: the SEED indexes with "search_document: ", but a
    # QUERY must use "search_query: " or recall quality silently degrades.
    seen = {}
    def fake_embed(text):
        seen["text"] = text
        return [0.0]
    monkeypatch.setattr(R, "_embed_query", fake_embed)
    monkeypatch.setattr(R, "_pg_connect", lambda: _FakeConn([]))

    R.search_vault("why always-on T1?", k=3)
    # _embed_query is the seam that owns the prefix; assert search_vault delegates
    # the raw query to it (the prefix is applied inside _embed_query, verified in
    # its own test below).
    assert seen["text"] == "why always-on T1?"


def test_embed_query_applies_search_query_prefix(monkeypatch):
    captured = {}
    def fake_post(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {"data": [{"embedding": [1.0, 2.0]}]}
    monkeypatch.setattr(R, "_embed_post", fake_post)

    vec = R._embed_query("VRAM headroom")
    assert vec == [1.0, 2.0]
    assert captured["payload"]["input"] == "search_query: VRAM headroom"


# ── L4 session_recall (Hermes FTS5, read-only) ──────────────────────────────────
def _make_hermes_db(path):
    import sqlite3
    c = sqlite3.connect(path)
    c.executescript(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,"
        " content TEXT, timestamp REAL);"
        "CREATE VIRTUAL TABLE messages_fts USING fts5(content);"
    )
    rows = [
        (1, "sess-abc", "user", "why did T1 offload to CPU last night?", 1000.0),
        (2, "sess-abc", "assistant", "T1 offloaded under VRAM pressure per §10.3.", 1001.0),
        (3, "sess-xyz", "user", "unrelated chatter about lunch", 1002.0),
    ]
    for r in rows:
        c.execute("INSERT INTO messages VALUES (?,?,?,?,?)", r)
        c.execute("INSERT INTO messages_fts(rowid, content) VALUES (?,?)", (r[0], r[3]))
    c.commit()
    c.close()


def test_session_recall_returns_matching_history_readonly(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    _make_hermes_db(str(db))
    monkeypatch.setattr(R, "_HERMES_STATE_DB", str(db))

    out = R.session_recall("offload", k=5)

    assert out, "expected an FTS5 hit for 'offload'"
    assert all(s.layer == "L4" for s in out)
    assert any("offload" in s.text.lower() for s in out)
    assert all("sess-abc" in s.source for s in out)   # the lunch row must not match
    # read-only: the file is unchanged and no -wal/-journal left behind
    assert not (tmp_path / "state.db-wal").exists()


# ── L6 doctrine_section (section-addressed, replaces the 4 KB head excerpt) ──────
_DOC = """# Memory Architecture

## §7 — Per-Layer Detail

### §7.6 L6 vault
Vault is human-curated Truth on NVMe.

### §7.7 L7 EverMemOS
EverMemOS consolidates MemCells into MemScenes on a cron cadence.
Foresight is a time-bounded field.

## §8 — Hermes
Hermes is the working-memory layer.
"""


def test_doctrine_section_returns_named_section_only(monkeypatch, tmp_path):
    f = tmp_path / "final_memory_architecture.md"
    f.write_text(_DOC)
    monkeypatch.setitem(R._DOCTRINE_FILES, "memory", f)

    snip = R.doctrine_section("memory", "§7.7")

    assert snip is not None
    assert snip.layer == "L6"
    assert "EverMemOS consolidates MemCells" in snip.text
    assert "§7.7" in snip.locator
    # bounded to the section: the NEXT section's body must not bleed in
    assert "Hermes is the working-memory layer" not in snip.text
    assert "Vault is human-curated" not in snip.text


def test_doctrine_section_missing_returns_none(monkeypatch, tmp_path):
    f = tmp_path / "final_memory_architecture.md"
    f.write_text(_DOC)
    monkeypatch.setitem(R._DOCTRINE_FILES, "memory", f)
    assert R.doctrine_section("memory", "§99.9") is None


def test_doctrine_section_empty_section_returns_none_not_preamble(monkeypatch, tmp_path):
    # An empty section must NOT silently return the file's first heading (the
    # preamble): `re.escape("")` + the zero-width lookahead matches column 0 of
    # every heading. Reachable from Phase-B _run_tool's args.get("section", "").
    f = tmp_path / "final_memory_architecture.md"
    f.write_text(_DOC)
    monkeypatch.setitem(R._DOCTRINE_FILES, "memory", f)
    assert R.doctrine_section("memory", "") is None
    assert R.doctrine_section("memory", "   ") is None


_DOC_CHILD_FIRST = """# Doc

### §7.7 Child Section
child body here

## §7 Parent Section
parent body here

## §8 Next
next body
"""


def test_doctrine_section_bare_parent_not_captured_by_child(monkeypatch, tmp_path):
    # Requesting bare "§7" must NOT substring-match the "§7.7" child heading that
    # appears first; the anchored match skips it and returns the real "§7" parent.
    f = tmp_path / "final_memory_architecture.md"
    f.write_text(_DOC_CHILD_FIRST)
    monkeypatch.setitem(R._DOCTRINE_FILES, "memory", f)
    snip = R.doctrine_section("memory", "§7")
    assert snip is not None
    assert "parent body here" in snip.text
    assert "child body here" not in snip.text


# ── L6 doctrine_search (heading-aware, name→section recall) ─────────────────────
_DOC_ARCH = """# Memory Architecture

## §7 — Per-Layer Detail

### §7.3 L3 — pgvector (Index: semantic)
L3 is pgvector over vault_note_chunks on monarch-postgres:5433.

### §7.6 L6 vault
Vault is human-curated Truth on NVMe.

## §11.3 L3 pgvector failure modes
A down embed service degrades L3 cleanly.
"""


def test_doctrine_search_finds_section_by_name_not_number(monkeypatch, tmp_path):
    f = tmp_path / "final_memory_architecture.md"
    f.write_text(_DOC_ARCH)
    monkeypatch.setattr(R, "_DOCTRINE_FILES", {"memory": f})
    out = R.doctrine_search("what backs L3?")
    assert out, "an architecture question by NAME must find the §-section"
    assert out[0].layer == "L6"
    assert "pgvector over vault_note_chunks" in out[0].text
    assert "§7.3" in out[0].locator


def test_doctrine_search_returns_bounded_section_not_whole_file(monkeypatch, tmp_path):
    f = tmp_path / "final_memory_architecture.md"
    f.write_text(_DOC_ARCH)
    monkeypatch.setattr(R, "_DOCTRINE_FILES", {"memory": f})
    out = R.doctrine_search("L3 backend")
    top = out[0]
    # bounded: the §7.3 hit must not bleed into the §7.6 sibling
    assert "Vault is human-curated" not in top.text


def test_doctrine_search_ranks_more_specific_heading_first(monkeypatch, tmp_path):
    f = tmp_path / "final_memory_architecture.md"
    f.write_text(_DOC_ARCH)
    monkeypatch.setattr(R, "_DOCTRINE_FILES", {"memory": f})
    # "L3 pgvector" matches the §11.3 heading on TWO tokens (l3, pgvector) vs the
    # §7.3 heading also on two (l3, pgvector) — both rank above unrelated headings.
    out = R.doctrine_search("L3 pgvector")
    assert all(s.layer == "L6" for s in out)
    assert any("§7.3" in s.locator for s in out)
    assert any("§11.3" in s.locator for s in out)


def test_doctrine_search_no_match_returns_empty(monkeypatch, tmp_path):
    f = tmp_path / "final_memory_architecture.md"
    f.write_text(_DOC_ARCH)
    monkeypatch.setattr(R, "_DOCTRINE_FILES", {"memory": f})
    assert R.doctrine_search("quarterly revenue forecast") == []
    assert R.doctrine_search("a") == []          # all tokens < 2 chars → no terms


def test_doctrine_search_skips_missing_file_without_raising(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_DOCTRINE_FILES", {"memory": tmp_path / "does_not_exist.md"})
    # must not raise even though a configured file is absent
    assert R.doctrine_search("L3 backend") == []


# ── shared snippet formatter (falsy-zero distance bug) ──────────────────────────
def test_format_snippet_tags_perfect_l3_match_and_skips_unranked():
    # A perfect L3 hit has distance 0.0 and MUST still show its (dist 0.00) tag — a
    # truthy-score check hid the strongest possible match. Non-ranked layers (score
    # 0.0 by convention) carry no spurious distance tag.
    assert "(dist 0.00)" in R.format_snippet(R.Snippet("L3", "f", "f §1", 0.0, "exact"))
    assert "(dist" not in R.format_snippet(R.Snippet("L6", "f", "f §7.7", 0.0, "doc"))


# ── L4 short-token tokenization (the stack's own 2-char vocabulary) ─────────────
def test_session_recall_matches_two_char_domain_token(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    _make_hermes_db(str(db))
    monkeypatch.setattr(R, "_HERMES_STATE_DB", str(db))
    # "T1" is a 2-char token. The old `> 2` filter dropped it (and T2/T4/L3/L4/L5/L7),
    # so this query tokenized to nothing meaningful and L4 silently returned no hits.
    out = R.session_recall("is T1 up", k=5)
    assert out, "2-char domain token 'T1' must survive FTS tokenization"
    assert any("T1" in s.text for s in out)


# ── gather() orchestrator: routing + degradation + budget + explicit §sections ──
def _snip(layer, text, score=0.1):
    return R.Snippet(layer=layer, source="s", locator=f"{layer}:loc",
                     score=score, text=text)


def test_gather_collects_routed_layers_and_degrades_without_raising(monkeypatch):
    monkeypatch.setattr(R, "search_vault", lambda q, k=5: [_snip("L3", "vault hit")])
    def boom(q, k=5):
        raise RuntimeError("hermes db locked")
    monkeypatch.setattr(R, "session_recall", boom)

    # "decide last session" routes to L4 (which fails) + L3 (which works).
    res = R.gather("what did we decide last session about offload?")

    assert any(s.layer == "L3" for s in res.snippets)        # working layer present
    assert not any(s.layer == "L4" for s in res.snippets)    # failed layer absent
    assert any("L4" in n for n in res.notes)                 # …but surfaced as a note
    # never raised into the turn
    assert isinstance(res.notes, list)


def test_gather_enforces_char_budget(monkeypatch):
    big = "x" * 400
    monkeypatch.setattr(R, "search_vault",
                        lambda q, k=5: [_snip("L3", big), _snip("L3", big), _snip("L3", big)])
    res = R.gather("why?", char_budget=500)
    assert len(res.snippets) == 1                            # 2nd would exceed 500
    assert any("truncat" in n.lower() for n in res.notes)


def test_gather_pulls_explicitly_referenced_section(monkeypatch):
    monkeypatch.setattr(R, "search_vault", lambda q, k=5: [])
    monkeypatch.setattr(R, "doctrine_section",
                        lambda key, sec: _snip("L6", f"section {sec} body")
                        if sec == "§7.7" and key == "memory" else None)
    res = R.gather("explain §7.7 please")
    assert any(s.layer == "L6" and "§7.7" in s.text for s in res.snippets)


def test_gather_prioritizes_explicit_section_over_fuzzy_hits(monkeypatch):
    # An operator naming "§7.7" is a HIGH-confidence signal. It must survive the
    # budget even when a large fuzzy L3 hit could otherwise consume it all.
    monkeypatch.setattr(R, "search_vault", lambda q, k=5: [_snip("L3", "z" * 7000)])
    monkeypatch.setattr(R, "doctrine_section",
                        lambda key, sec: _snip("L6", "the §7.7 answer body " + "y" * 2000)
                        if sec == "§7.7" and key == "memory" else None)
    res = R.gather("explain §7.7", char_budget=8000)
    assert any(s.layer == "L6" for s in res.snippets), \
        "explicit §section must outrank fuzzy L3 under budget pressure"


def test_gather_pulls_doctrine_search_for_architecture_question(monkeypatch):
    # An architecture question by NAME (no literal §number) must still land the
    # authoritative L6 section via doctrine_search, in the priority tier.
    monkeypatch.setattr(R, "search_vault", lambda q, k=5: [_snip("L3", "fuzzy vault hit")])
    monkeypatch.setattr(R, "doctrine_search",
                        lambda q, k=5: [_snip("L6", "L3 is pgvector on :5433")])
    res = R.gather("what backs L3?")
    assert any(s.layer == "L6" and "pgvector" in s.text for s in res.snippets)


def test_gather_doctrine_search_survives_budget_over_fuzzy_hit(monkeypatch):
    # The named doctrine section is priority-tier: a large fuzzy L3 hit must not
    # evict it under budget pressure (same guarantee as an explicit §reference).
    monkeypatch.setattr(R, "search_vault", lambda q, k=5: [_snip("L3", "z" * 7000)])
    monkeypatch.setattr(R, "doctrine_search",
                        lambda q, k=5: [_snip("L6", "the L3 backend answer " + "y" * 1000)])
    res = R.gather("what backs L3?", char_budget=8000)
    assert any(s.layer == "L6" for s in res.snippets)


def test_gather_dedups_named_and_numbered_same_section(monkeypatch):
    # Operator both types "§7.3" AND names "L3": the same section body must appear
    # once, not twice. Dedup is on (source, text) so differing locators don't fool it.
    SECTION = R.Snippet("L6", "memory.md", "memory.md §7.3", 0.0, "the one true §7.3 body")
    NAMED   = R.Snippet("L6", "memory.md", "memory.md §7.3 L3 — pgvector", 0.0, "the one true §7.3 body")
    monkeypatch.setattr(R, "search_vault", lambda q, k=5: [])
    monkeypatch.setattr(R, "doctrine_section",
                        lambda key, sec: SECTION if (sec == "§7.3" and key == "memory") else None)
    monkeypatch.setattr(R, "doctrine_search", lambda q, k=5: [NAMED])
    res = R.gather("what backs L3 — see §7.3")
    bodies = [s.text for s in res.snippets if s.text == "the one true §7.3 body"]
    assert len(bodies) == 1, "the same section pulled by number AND name must dedup"


def test_gather_no_spurious_l6_not_wired_note(monkeypatch):
    # L6 is served from the priority tier, NOT _LAYER_FUNC_NAMES; the routed loop
    # must skip it rather than emit a "L6 not wired in Phase A" note.
    monkeypatch.setattr(R, "search_vault", lambda q, k=5: [_snip("L3", "hit")])
    monkeypatch.setattr(R, "doctrine_search", lambda q, k=5: [])
    res = R.gather("what backs L3?")
    assert not any("L6 not wired" in n for n in res.notes)


# ── L5 code_structure (codebase-memory search_code) ─────────────────────────────
def test_code_structure_maps_search_code_results_to_snippets(monkeypatch):
    monkeypatch.setattr(R, "_l5_cli", lambda pattern, project: [
        {"node": "classify", "qualified_name":
         "home-operator-projects-loki.loki.authority.AuthorityGate.classify",
         "label": "Method", "file": "loki/authority.py",
         "start_line": 257, "end_line": 265},
    ])
    out = R.code_structure("AuthorityGate", k=5)
    assert len(out) == 1
    assert out[0].layer == "L5"
    assert "loki/authority.py" in out[0].locator and "257" in out[0].locator
    assert "AuthorityGate.classify" in out[0].text


# ── L7 temporal_recall (EverCore search) ────────────────────────────────────────
def test_temporal_recall_maps_episodes_to_snippets(monkeypatch):
    monkeypatch.setattr(R, "_l7_search", lambda query, k: {
        "episodes": [{"id": "e1", "content": "VRAM headroom grew 8→11.5 GB after the T4 move"}],
        "raw_messages": [],
    })
    out = R.temporal_recall("how did vram headroom change?", k=3)
    assert out and out[0].layer == "L7"
    assert "11.5 GB" in out[0].text
