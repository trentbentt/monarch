"""Host-resource wire (resources.ram / resources.cpu) in process.py.

Before this, resources.ram and resources.cpu were schema placeholders no
listener ever wrote (updated_at stayed None; free_mb read the 96 GB default,
load averages read 0.0). process.py owns per-tier /proc reads, so host-level
MemAvailable + loadavg belong here.
"""
from datetime import datetime, timezone

from loki.listeners import process
from loki.schema import SystemModel

_MEMINFO = """MemTotal:       98757312 kB
MemFree:         5720000 kB
MemAvailable:   57200640 kB
Buffers:          204800 kB
Cached:         40960000 kB
"""


def test_parse_mem_available_mb_reads_memavailable_not_memfree():
    # 57200640 kB / 1024 = 55860 MB (available, the reclaim-aware number —
    # NOT MemFree, which would read an alarming ~5.5 GB on a healthy box).
    assert process._parse_mem_available_mb(_MEMINFO) == 55860


def test_parse_mem_available_mb_absent_returns_none():
    assert process._parse_mem_available_mb("MemTotal: 98757312 kB\n") is None


def test_apply_host_resources_populates_ram_and_cpu():
    model = SystemModel()
    now = datetime.now(timezone.utc)
    # Baseline: both domains are unwritten placeholders.
    assert model.resources.cpu.updated_at is None
    assert model.resources.ram.updated_at is None

    process._apply_host_resources(model, (0.71, 0.65, 0.44), 55860, now)

    assert model.resources.cpu.load_avg_1m == 0.71
    assert model.resources.cpu.load_avg_5m == 0.65
    assert model.resources.cpu.load_avg_15m == 0.44
    assert model.resources.cpu.updated_at == now
    assert model.resources.ram.free_mb == 55860
    assert model.resources.ram.updated_at == now


def test_apply_host_resources_none_reads_do_not_fake_freshness():
    model = SystemModel()
    now = datetime.now(timezone.utc)
    process._apply_host_resources(model, None, None, now)
    # A failed read must NOT stamp updated_at — a stale/absent probe reads as a
    # gap, never fake-fresh (mirrors the metrics sampler's staleness honesty).
    assert model.resources.cpu.updated_at is None
    assert model.resources.ram.updated_at is None
