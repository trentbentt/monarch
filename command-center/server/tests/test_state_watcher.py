"""StateWatcher behaviour: prime, change detection, torn-read resilience."""
import json

import pytest

from reader.state_watcher import StateWatcher


@pytest.mark.asyncio
async def test_primes_and_reads(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_updated": "x", "daemon_pid": 1}))
    w = StateWatcher(path=p, poll_sec=0.05)
    await w.start()
    try:
        assert w.current()["daemon_pid"] == 1
    finally:
        await w.stop()


@pytest.mark.asyncio
async def test_torn_read_keeps_prior_snapshot(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"v": 1}))
    w = StateWatcher(path=p, poll_sec=0.05)
    await w.start()
    try:
        assert w.current()["v"] == 1
        p.write_text("{ this is not valid json")   # simulate mid-write torn read
        import asyncio
        await asyncio.sleep(0.2)
        assert w.current()["v"] == 1               # prior good snapshot retained
    finally:
        await w.stop()


@pytest.mark.asyncio
async def test_subscribe_yields_on_change(tmp_path):
    import asyncio
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"v": 1}))
    w = StateWatcher(path=p, poll_sec=0.05)
    await w.start()
    try:
        sub = w.subscribe()
        first = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
        assert first["v"] == 1
        p.write_text(json.dumps({"v": 2}))
        nxt = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
        assert nxt["v"] == 2
        await sub.aclose()
    finally:
        await w.stop()
