# -*- coding: utf-8 -*-
"""Unit tests for farming/tools/farming_snapshot.py (FARM-048).

Covers the on-chain free-cash read and the farming_daily_cash upsert, with the
critical None (RPC failure) vs 0.0 (empty wallet) distinction on BOTH the read
and the write paths.

farming_snapshot.py imports py_clob_client_v2 at module level (not installed on
S1); we stub the minimal surface before import, scoped to a fixture and reverted
in finally — same approach as tests/unit/test_farming_daemon_reconcile.py. web3
is a real installed dependency here, left intact.
"""
import os
import sys
import types

import pytest

_TOOLS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "farming", "tools")
)


def _install_clob_stub():
    """Insert a fake py_clob_client_v2 (+ clob_types.TradeParams) into
    sys.modules so `import farming_snapshot` succeeds without the real SDK.
    Returns the list of sys.modules keys it added, for cleanup."""
    added = []
    if "py_clob_client_v2" not in sys.modules:
        clob_mod = types.ModuleType("py_clob_client_v2")
        clob_mod.ClobClient = type("ClobClient", (), {})
        sys.modules["py_clob_client_v2"] = clob_mod
        added.append("py_clob_client_v2")

        types_mod = types.ModuleType("py_clob_client_v2.clob_types")
        types_mod.TradeParams = type("TradeParams", (), {})
        sys.modules["py_clob_client_v2.clob_types"] = types_mod
        added.append("py_clob_client_v2.clob_types")
    return added


@pytest.fixture
def snap():
    added_mods = _install_clob_stub()
    added_path = False
    if _TOOLS_DIR not in sys.path:
        sys.path.insert(0, _TOOLS_DIR)
        added_path = True
    sys.modules.pop("farming_snapshot", None)
    try:
        import farming_snapshot
        yield farming_snapshot
    finally:
        sys.modules.pop("farming_snapshot", None)
        for m in added_mods:
            sys.modules.pop(m, None)
        if added_path:
            try:
                sys.path.remove(_TOOLS_DIR)
            except ValueError:
                pass


def _make_fake_web3(ret_bytes=None, raise_exc=None):
    """Build a fake Web3 class for monkeypatching farming_snapshot.Web3.

    eth.call returns ret_bytes, or raises raise_exc if provided. HTTPProvider /
    to_bytes are stubbed (their return values do not affect the faked call)."""
    class FakeEth:
        def call(self, tx):
            if raise_exc is not None:
                raise raise_exc
            return ret_bytes

    class FakeWeb3:
        def __init__(self, provider):
            self.eth = FakeEth()

        @staticmethod
        def HTTPProvider(url, request_kwargs=None):
            return url

        def to_bytes(self, hexstr=None):
            return b"\x00" * 20

    return FakeWeb3


class _FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur
        self.committed = False

    def cursor(self):
        return self._cur

    def commit(self):
        self.committed = True

    def close(self):
        pass


def test_read_cash_balance_success(snap, monkeypatch):
    # 123.45 pUSD = 123_450_000 raw (1e6)
    ret = (123_450_000).to_bytes(32, "big")
    monkeypatch.setattr(snap, "Web3", _make_fake_web3(ret_bytes=ret))
    assert snap.read_cash_balance() == pytest.approx(123.45)


def test_read_cash_balance_rpc_failure_returns_none(snap, monkeypatch):
    # All RPCs fail -> None, NOT 0.0 (0.0 would be misread as empty wallet).
    monkeypatch.setattr(
        snap, "Web3", _make_fake_web3(raise_exc=RuntimeError("rpc down"))
    )
    result = snap.read_cash_balance()
    assert result is None
    assert result != 0.0


def test_upsert_cash_none_stores_sql_null(snap, monkeypatch):
    cur = _FakeCursor()
    conn = _FakeConn(cur)
    monkeypatch.setattr(snap, "get_db_connection", lambda: conn)

    snap.upsert_cash("2026-07-19", None)

    assert len(cur.calls) == 1
    _, params = cur.calls[0]
    assert params["snap_date"] == "2026-07-19"
    assert params["free_cash_pusd"] is None  # SQL NULL, never coerced to 0
    assert conn.committed


def test_upsert_cash_zero_distinct_from_none(snap, monkeypatch):
    cur = _FakeCursor()
    conn = _FakeConn(cur)
    monkeypatch.setattr(snap, "get_db_connection", lambda: conn)

    snap.upsert_cash("2026-07-19", 0.0)

    _, params = cur.calls[0]
    assert params["free_cash_pusd"] == 0.0
    assert params["free_cash_pusd"] is not None


def test_upsert_cash_value(snap, monkeypatch):
    cur = _FakeCursor()
    conn = _FakeConn(cur)
    monkeypatch.setattr(snap, "get_db_connection", lambda: conn)

    snap.upsert_cash("2026-07-19", 456.78)

    _, params = cur.calls[0]
    assert params["free_cash_pusd"] == pytest.approx(456.78)
    assert conn.committed