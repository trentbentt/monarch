"""
Drift guards for the supervisor system prompt's memory-architecture model.

The prompt carries a *resident* description of the memory architecture (the L1-L7
layers, the four roles, the conflict rule, and which retrieval tool reaches which
layer). That description is a static snapshot of canonical doctrine
(final_memory_architecture.md) and of retrieval.py's behaviour — exactly the kind
of copy that silently goes stale. The previous version said "L1 Redis through the
L4 agentic layer", stopping at L4 and conflating the L-numbering with the four
roles; nothing caught it because no test pinned the prompt's content.

These tests pin the *facts*, not the prose, so the prompt can be reworded freely
but cannot drift away from the architecture it describes or from the tool→layer
wiring the code actually implements.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from loki.supervisor import retrieval
from loki.supervisor.client import load_system_prompt

PROMPT = load_system_prompt()

_ARROW = r"\s*(?:→|->)\s*"
_CANONICAL_DOCTRINE = Path.home() / "vault/final_memory_architecture.md"


def test_prompt_names_all_seven_layers():
    """Every operational layer L1-L7 must be described. Guards against the exact
    regression we fixed: a prompt that stops at L4 and omits L5/L6/L7."""
    missing = [f"L{n}" for n in range(1, 8)
               if not re.search(rf"\bL{n}\b", PROMPT)]
    assert not missing, f"system prompt omits memory layer(s): {missing}"


def test_prompt_has_no_truncated_layer_phrasing():
    """The specific stale phrasing that conflated the L-numbering with the four
    roles must not reappear."""
    assert "L4 agentic layer" not in PROMPT


def test_prompt_names_the_four_roles_and_arbiter_identity():
    """The four-role framing (memory-arch §3) is the load-bearing mental model;
    'Arbiter' is the distinctive one and is the supervisor's own identity (§3.4)."""
    for role in ("Truth", "Index", "Memory", "Arbiter"):
        assert role in PROMPT, f"system prompt drops the '{role}' role"
    # The supervisor must know it IS the single Arbiter, not merely that one exists.
    assert re.search(r"Arbiter[^.]*\byou\b|\byou\b[^.]*Arbiter", PROMPT, re.I)


def test_prompt_states_the_single_conflict_rule():
    """memory-arch §4: Truth is primary, everything else derived."""
    assert re.search(r"Truth is primary|Truth\s+primary", PROMPT)


def test_prompt_tool_to_layer_map_matches_retrieval_code():
    """The strongest guard: the prompt tells the model which layer each RETRIEVE
    tool reaches. That claim must match the layer each function actually emits.
    Ground truth is retrieval._LAYER_FUNC_NAMES (L3/L4/L5/L7) plus the doctrine
    tools (L6). If a tool is rewired to a different layer and the prompt is not
    updated, this fails."""
    truth = {fn: layer for layer, fn in retrieval._LAYER_FUNC_NAMES.items()}
    truth["doctrine_search"] = "L6"
    truth["doctrine_section"] = "L6"

    for tool, layer in truth.items():
        # Tolerate backticks and the "doctrine_search/doctrine_section"-joined pair
        # sharing one arrow; pin only that the tool maps to its real layer.
        m = re.search(re.escape(tool) + r"[`/\w]*" + _ARROW + r"(L[1-7])", PROMPT)
        assert m, f"prompt does not map retrieval tool {tool!r} to any layer"
        assert m.group(1) == layer, (
            f"prompt maps {tool}→{m.group(1)} but retrieval.py emits {layer}")


def test_prompt_marks_L1_L2_as_off_the_retrieval_path():
    """L1/L2 (Redis/Postgres) are operational Truth read via live-state / loki-q,
    not via the retrieval tools. The prompt must say so, so the model never claims
    to have 'retrieved' live trading/Postgres state it cannot reach this way."""
    assert "loki-q" in PROMPT
    assert re.search(r"L1 and L2|L1/L2", PROMPT)


def test_prompt_defers_layer_specifics_to_retrieval():
    """Method-based contract: the volatile §7 roster/implementations must be
    RETRIEVED, not recited. The prompt has to point at §7 and tell the model not to
    recite a roster — otherwise we are back to a static photocopy that drifts."""
    assert re.search(r"§7", PROMPT), "prompt must point layer-specifics at §7"
    assert re.search(r"retriev", PROMPT, re.I)
    assert re.search(r"do not recite|don't recite|not\s+recite|never\s+recite",
                     PROMPT, re.I), "prompt must forbid reciting a memorized roster"


def test_prompt_does_not_hardcode_volatile_implementations():
    """The drift-prone failure was naming each layer's backend (Redis/pgvector/
    Hermes/EverMemOS/Codebase-Memory) as a fixed roster. Those implementation names
    belong in retrieved §7 doctrine, not frozen in the prompt. If one reappears as a
    resident fact, the photocopy is back."""
    volatile = ["Redis", "Postgres", "pgvector", "Hermes", "EverMemOS",
                "Codebase-Memory", "Nexus", "Obsidian", "MemCell", "MemScene",
                "Tree-Sitter", "FTS5"]
    leaked = [name for name in volatile if name in PROMPT]
    assert not leaked, (
        f"prompt hardcodes volatile layer implementation(s) {leaked} — these are "
        f"§7 doctrine, retrieve them rather than reciting")


def test_prompt_covers_every_layer_the_doctrine_defines():
    """Cross-repo drift guard (skipped when the vault isn't on disk): every layer
    the doctrine gives a §7 per-layer detail heading must be named in the prompt.

    The roster is parsed from the §7.N headings ("### §7.1 L1 — Redis …"), NOT from
    any bare 'L<n>' token — so a stray mention (e.g. an L8 ruled out in §14 prose)
    is ignored, but a real new §7.8 L8 layer is required in the prompt and fails
    this test until synced. (The earlier version capped the roster at L7, which
    silently exempted exactly the future-L8 case it claimed to guard.)"""
    if not _CANONICAL_DOCTRINE.exists():
        pytest.skip("canonical memory-architecture doctrine not present on disk")
    doctrine = _CANONICAL_DOCTRINE.read_text(errors="replace")
    roster = set(re.findall(r"§7\.\d+\s+L(\d)", doctrine))
    assert roster, "could not parse the §7 per-layer roster from doctrine"
    missing = sorted(n for n in roster if not re.search(rf"\bL{n}\b", PROMPT))
    assert not missing, (
        f"prompt omits layer(s) {['L'+n for n in missing]} that doctrine §7 "
        f"defines — re-sync the resident model")
