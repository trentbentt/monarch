#!/usr/bin/env python3
"""Generate a sanitised test fixture from the live Loki state.json.

Reads ~/.local/state/loki/state.json, scrubs the operator domain (session ids,
input timestamps) so no operator-identifying data is committed, and writes
server/tests/fixtures/state.sample.json. The shape is preserved exactly so tests
exercise the real contract.

Usage:  python3 scripts/make_fixture.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SRC = Path(os.environ.get("CC_STATE_PATH", str(Path.home() / ".local/state/loki/state.json")))
DST = Path(__file__).resolve().parent.parent / "server/tests/fixtures/state.sample.json"


def scrub(state: dict) -> dict:
    op = state.get("operator")
    if isinstance(op, dict):
        op["active_session_id"] = None
        op["last_input_detected"] = None
        op["updated_at"] = None
    state["daemon_pid"] = 0
    return state


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"source state not found: {SRC}")
    state = json.loads(SRC.read_text())
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(json.dumps(scrub(state), indent=2, sort_keys=True))
    print(f"wrote fixture: {DST}  ({DST.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
