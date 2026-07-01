"""Authority-ledger contract — the on-disk ``authority.json`` record shape.

Two SEPARATE Loki code paths touch this shape:
  * writer — ``loki.authority.AuthorityLedger`` persists ``ActionRecord.model_dump()``
  * reader — ``loki.supervisor.context.load_ledger()`` projects it for the supervisor

They disagreed on the field names: the reader looked for ``clean_runs`` /
``lifecycle``, which never existed on disk — the writer persists
``clean_run_count`` / ``state``. The supervisor's grounded trust block was
therefore always null, and nothing caught it because there was no shared schema
and no test crossing the boundary. This contract + ``tests/test_conformance.py``
are that guard.
"""
from __future__ import annotations

# Canonical authority.json record field names. The writer must serialize
# exactly this set; the reader must key off these names.
LEDGER_FIELDS = frozenset({
    "action_id",
    "description",
    "current_tier",
    "target_tier",
    "clean_run_count",
    "state",
    "total_runs",
    "last_fired",
    "last_outcome",
    "demotion_reason",
})

# The two trust fields the supervisor grounds its answers on — the exact fields
# the original bug read under the wrong names.
TRUST_FIELDS = frozenset({"clean_run_count", "state"})
