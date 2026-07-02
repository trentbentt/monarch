"""Bridge to the Loki supervisor layer (T1 read-and-propose console).

The dashboard's chat console talks to THIS module, which drives the supervisor
exactly as the CLI does: SupervisorClient for a plain grounded answer,
SupervisorAgent for the bounded ReAct `--deep` investigation. Both route through
the local LiteLLM router (port 4000), so the supervisor stays fully on-box and
inherits the stack's own model routing/budgets.

Safety posture is unchanged: this is the read path. The supervisor holds no
authority — it answers and (when enabled elsewhere) proposes into the daemon's
gate. Nothing here writes proposals; the console is conversation only.

Degrades gracefully: if loki can't be imported or the router is down, the
caller gets a clear note instead of a 500 — the chat never hard-fails.
"""
from __future__ import annotations

import logging
import os
import sys

import config

logger = logging.getLogger(__name__)

# The supervisor lives in the loki package, not pip-installed into this venv.
# Resolve its root once and put it on the path so `from loki.supervisor ...`
# works without coupling the two repos' packaging.
LOKI_ROOT = config.LOKI_ROOT   # single source of truth (defaults to in-repo loki/)


def _load_router_key() -> None:
    """The SupervisorClient authenticates to the LOCAL LiteLLM router with the
    master key (LiteLLM 401s unauthenticated calls). The daemon's own units
    source it from api_keys.env; this process may not have it in its environment,
    so lift it from the same file the rest of the stack uses. No provider
    credential is handled here — only the local router key."""
    if os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("LITELLM_API_KEY"):
        return
    try:
        for line in config.API_KEYS_ENV.read_text().splitlines():
            line = line.strip()
            # The file is shell-sourced by the rest of the stack, so every entry
            # is `export NAME=value`. Strip the `export ` prefix before matching —
            # without this the key is never lifted and the router 401s (which the
            # loki client surfaces, misleadingly, as "router unreachable").
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            name, sep, val = line.partition("=")
            name = name.strip()
            if sep and name in ("LITELLM_MASTER_KEY", "LITELLM_API_KEY"):
                val = val.strip().strip('"').strip("'")
                if val:
                    os.environ.setdefault(name, val)
    except OSError:
        pass  # key absent → client still tries; router may allow it


def _supervisor():
    """Lazy import so a missing/renamed loki tree degrades to a clear message
    instead of crashing the whole API at startup."""
    if str(LOKI_ROOT) not in sys.path:
        sys.path.insert(0, str(LOKI_ROOT))
    from loki.supervisor import SupervisorAgent, SupervisorClient  # noqa: WPS433
    return SupervisorClient, SupervisorAgent


def scope_preamble(payload: dict) -> str:
    """Compose the scope block the deep-dive prepends to a question so the
    supervisor answers in-context. Derived from a provider's deep_payload
    (manifest + live detail). Keeps it compact — this rides in front of every
    scoped turn, and the supervisor's own retrieval pulls the full source.

    Read-only by construction: this is context, not instruction to act.
    """
    if not payload:
        return ""
    m = payload.get("manifest", {}) or {}
    d = payload.get("detail", {}) or {}
    lines = [
        f"## Operator is viewing the {payload.get('label', payload.get('key'))} "
        f"deep-dive (status: {payload.get('status', 'unknown')})",
    ]
    if m.get("lede"):
        lines.append(m["lede"])

    items = m.get("items") or []
    if items:
        lines.append("\nSections / source behind this domain:")
        for it in items:
            bits = [f"- {it.get('name')}: {it.get('what', '')}".rstrip()]
            if it.get("repo"):
                bits.append(f"    repo: {it['repo']}")
            if it.get("doctrine"):
                bits.append(f"    doctrine: {', '.join(it['doctrine'])}")
            if it.get("stages"):
                stages = " → ".join(s.get("label", s.get("key", "")) for s in it["stages"])
                bits.append(f"    stages: {stages}")
            lines.append("\n".join(bits))

    facts = d.get("facts") or []
    if facts:
        readout = "; ".join(
            f"{f.get('label')}={f.get('value')}"
            + (f" ({f.get('sub')})" if f.get("sub") else "")
            for f in facts
        )
        lines.append(f"\nLive readout: {readout}")
    for note in (d.get("notes") or []):
        lines.append(f"Note: {note}")

    if m.get("doctrine"):
        lines.append(f"\nDomain doctrine: {', '.join(m['doctrine'])}")

    lines.append(
        "\nAnswer the operator's question in this context. When it bears on "
        "behavior, cite the specific files and doctrine sections named above; "
        "retrieve their contents if you need them. You remain read-only."
    )
    return "\n".join(lines)


def ask(question: str, deep: bool = False, preamble: str | None = None) -> dict:
    """Answer one operator turn. `deep` runs the agentic investigation loop;
    otherwise a single grounded turn. Blocking (model call) — callers should run
    this off the event loop (see routes.supervisor_ask)."""
    question = (question or "").strip()
    if not question:
        return {"answer": "", "error": "empty question", "deep": deep}

    _load_router_key()
    try:
        SupervisorClient, SupervisorAgent = _supervisor()
    except Exception as exc:  # noqa: BLE001 — import/env failure must not 500
        # Log the detail server-side; return a generic note. Interpolating
        # LOKI_ROOT + the raw exception leaked absolute paths + dependency layout
        # to the client (the sibling ask-failure branch below was already fixed —
        # this one wasn't; review B4).
        logger.warning("supervisor import failed (root=%s): %s", LOKI_ROOT, exc)
        return {
            "answer": "[supervisor layer unavailable — see server logs]",
            "error": "import_failed",
            "deep": deep,
        }

    # The scope preamble rides in front of the question so the supervisor's own
    # retrieval (Phase A/C) sees the section's repos/doctrine and grounds on them.
    scoped = f"{preamble}\n\n## Question\n{question}" if preamble else question

    try:
        if deep:
            answer = SupervisorAgent().investigate(scoped)
        else:
            answer = SupervisorClient().ask(scoped)
    except Exception as exc:  # noqa: BLE001 — never surface a traceback to chat
        # Log the detail server-side; return a generic note. The raw exception
        # string leaks LOKI_ROOT absolute paths + dependency layout to clients.
        logger.warning("supervisor ask failed: %s", exc)
        return {
            "answer": "[supervisor error while answering — see server logs]",
            "error": "ask_failed",
            "deep": deep,
        }

    model = os.environ.get("LOKI_SUPERVISOR_MODEL", "qwen3.6-consultancy")
    return {"answer": answer, "deep": deep, "model": model, "error": None}
