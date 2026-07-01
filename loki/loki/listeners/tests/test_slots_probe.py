"""Tests for the llama-server /slots burst-activity probe.

Verified live against the running build: GET /slots returns a JSON array of slot
objects each carrying `is_processing` (bool). The probe counts processing slots
so the §10.3 eviction rule can idle-guard: 0 = safe to evict, >0 = busy, None =
endpoint unavailable / unparseable (UNKNOWN — never treated as idle).
"""

import json
import urllib.error

import pytest

from loki.listeners import tier_health


class _FakeResp:
    def __init__(self, body, status=200):
        self._body = body.encode() if isinstance(body, str) else body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(monkeypatch, resp_or_exc):
    def fake(req, timeout=None):
        if isinstance(resp_or_exc, Exception):
            raise resp_or_exc
        return resp_or_exc
    monkeypatch.setattr(tier_health.urllib.request, "urlopen", fake)


def test_slots_active_count_idle(monkeypatch):
    _patch_urlopen(monkeypatch, _FakeResp(json.dumps([{"id": 0, "is_processing": False}])))
    assert tier_health._slots_active_count(8083) == 0


def test_slots_active_count_busy(monkeypatch):
    _patch_urlopen(monkeypatch, _FakeResp(json.dumps([
        {"id": 0, "is_processing": True},
        {"id": 1, "is_processing": False},
    ])))
    assert tier_health._slots_active_count(8083) == 1


def test_slots_active_count_unavailable_returns_none(monkeypatch):
    _patch_urlopen(monkeypatch, urllib.error.URLError("connection refused"))
    assert tier_health._slots_active_count(8083) is None


def test_slots_active_count_non_list_returns_none(monkeypatch):
    # /slots disabled in some builds returns an error object, not an array.
    _patch_urlopen(monkeypatch, _FakeResp(json.dumps({"error": "slots endpoint disabled"})))
    assert tier_health._slots_active_count(8083) is None
