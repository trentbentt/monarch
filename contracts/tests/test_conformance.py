"""Cross-boundary conformance: every producer and consumer of a shared shape
must agree with contracts/. This is the test the convention-coupled seams
lacked — it fails loudly if Loki's ledger writer, Loki's ledger reader, or the
Command Center state shape drift from the contract.

Run with the inference venv (needs Loki's deps):
    ~/venv/inference/bin/python3 -m pytest contracts/tests -q
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]      # monarch/
sys.path.insert(0, str(_ROOT))                    # `import contracts`
sys.path.insert(0, str(_ROOT / "loki"))           # `import loki.*`

from contracts.ledger import LEDGER_FIELDS, TRUST_FIELDS
from contracts.state import STATE_DOMAINS


def test_loki_writer_matches_ledger_contract():
    """AuthorityLedger persists ActionRecord.model_dump(); its field set IS the
    on-disk ledger shape and must equal the contract."""
    from loki.schema import ActionRecord
    assert set(ActionRecord.model_fields) == set(LEDGER_FIELDS)


def test_loki_reader_reads_contract_keys(tmp_path, monkeypatch):
    """supervisor.context.load_ledger must read the contract's trust keys
    (clean_run_count/state). The exact bug was it read clean_runs/lifecycle,
    which never existed on disk — nulling the supervisor's grounded block."""
    from loki.supervisor import context
    rec = {k: None for k in LEDGER_FIELDS}
    rec.update({"current_tier": "tier_2", "clean_run_count": 9, "state": "eligible"})
    p = tmp_path / "authority.json"
    p.write_text(json.dumps({"actions": {"restore_t1_reasoning": rec}}))
    monkeypatch.setattr(context, "LEDGER_PATH", p)
    row = context.load_ledger()[0]
    assert row["clean_runs"] == 9          # mapped from clean_run_count
    assert row["lifecycle"] == "eligible"  # mapped from state


def test_trust_fields_subset_of_ledger_contract():
    assert set(TRUST_FIELDS) <= set(LEDGER_FIELDS)


def test_state_json_domains_match_contract():
    """The real-shaped state fixture the Command Center tests against must carry
    exactly the contract's domains — a domain rename in Loki surfaces here."""
    fixture = _ROOT / "command-center" / "server" / "tests" / "fixtures" / "state.sample.json"
    keys = set(json.loads(fixture.read_text()).keys())
    assert keys == set(STATE_DOMAINS)


def test_loki_state_writer_matches_contract():
    """The state.json PRODUCER (loki's SystemModel) must equal the contract's
    domains — mirroring test_loki_writer_matches_ledger_contract for the ledger.
    The fixture check above only guards a hand-maintained sample; without this,
    loki could rename/add a SystemModel domain and the Command Center would read
    `state.get(<old>)` → {} with NOTHING failing (review H8). This binds the real
    writer to the contract so producer drift fails loudly."""
    from loki.schema import SystemModel
    assert set(SystemModel.model_fields) == set(STATE_DOMAINS)


def test_loki_schema_version_matches_contract():
    """The state.json PRODUCER's schema_version must equal the contract's. This
    makes the version a real coordination point: bumping it in loki without
    updating the contract (and the consumers that key off it) fails here, instead
    of the field being an inert label nothing checks (review A4)."""
    from contracts.state import STATE_SCHEMA_VERSION
    from loki.schema import SystemModel
    assert SystemModel.model_fields["schema_version"].default == STATE_SCHEMA_VERSION


def test_schema_skew_helper_flags_mismatch():
    """The skew helper a reader uses to detect a state.json written by a different
    loki version: None when current, a note on any mismatch (incl. missing)."""
    from contracts.state import schema_skew, STATE_SCHEMA_VERSION
    assert schema_skew(STATE_SCHEMA_VERSION) is None
    assert schema_skew("9.9.9") is not None
    assert schema_skew(None) is not None


def test_cc_reads_declared_snippet_fields():
    """command-center's retrieval_bridge reads Snippet fields via getattr with
    silent defaults; assert they exist on loki's Snippet and that Snippet is in
    the module's declared public surface, so a loki rename fails loudly here
    instead of rendering score=0.0/text='' as if real (review A3)."""
    import dataclasses
    from loki.supervisor import retrieval
    assert "Snippet" in retrieval.__all__
    fields = {f.name for f in dataclasses.fields(retrieval.Snippet)}
    assert {"layer", "source", "locator", "score", "text"} <= fields
