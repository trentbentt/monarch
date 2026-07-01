"""Connection-lifecycle tests for QuotaListener.

The listener polls every 60s. Opening a fresh psycopg2 connection each poll pays
a TCP handshake + auth round-trip every minute for the lifetime of the daemon.
These tests pin the contract: reuse one connection across polls, set autocommit
(a read-only poller must not sit idle-in-transaction), and transparently
reconnect after a reset or a server-dropped connection.
"""

import pytest

from loki.listeners import quota


class _FakeConn:
    def __init__(self):
        self.closed = 0
        self.autocommit = False
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        self.closed = 1


class _FakePsycopg2:
    def __init__(self):
        self.connect_calls = 0

    def connect(self, *args, **kwargs):
        self.connect_calls += 1
        return _FakeConn()


@pytest.fixture
def fake_pg(monkeypatch):
    fp = _FakePsycopg2()
    monkeypatch.setattr(quota, "psycopg2", fp)
    return fp


def test_get_conn_reuses_connection_across_polls(fake_pg):
    q = quota.QuotaListener()
    c1 = q._get_conn("postgresql://x")
    c2 = q._get_conn("postgresql://x")
    assert c1 is c2
    assert fake_pg.connect_calls == 1


def test_get_conn_sets_autocommit(fake_pg):
    q = quota.QuotaListener()
    c = q._get_conn("postgresql://x")
    assert c.autocommit is True


def test_reset_conn_closes_and_forces_reconnect(fake_pg):
    q = quota.QuotaListener()
    c1 = q._get_conn("postgresql://x")
    q._reset_conn()
    assert c1.close_calls == 1
    c2 = q._get_conn("postgresql://x")
    assert c2 is not c1
    assert fake_pg.connect_calls == 2


def test_get_conn_reconnects_when_server_dropped(fake_pg):
    q = quota.QuotaListener()
    c1 = q._get_conn("postgresql://x")
    c1.closed = 1  # server dropped the connection
    c2 = q._get_conn("postgresql://x")
    assert c2 is not c1
    assert fake_pg.connect_calls == 2
