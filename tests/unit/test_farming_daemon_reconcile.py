# -*- coding: utf-8 -*-
"""Unit test for FARM-036: reconcile_orders() must not let a get_open_orders()
API error masquerade as a confirmed "two-sided" book.

farming_daemon.py imports py_clob_client_v2 at module level, which is not
installed in this (S1) environment. We stub the minimal surface it needs
before import so the module loads without the real CLOB SDK. (web3 IS a real
installed dependency here — we leave it alone.)

All sys.path / sys.modules mutation happens INSIDE the fixture and is
reverted in a finally block: mutating them at module-import time (collection)
previously made `executor/` shadow the top-level name `executor` for every
other test module collected afterward (executor/ also contains an unrelated
executor/executor.py) — see FARM-036 review. Keeping the mutation scoped to
the fixture's lifetime avoids cross-file collection order-dependence.
"""

import os
import sys
import types

import pytest

_EXECUTOR_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "executor")
)


def _install_clob_stub():
    """Insert a fake py_clob_client_v2 (+ order_builder.constants) into
    sys.modules so `import farming_daemon` succeeds without the real SDK.
    Returns the list of sys.modules keys it added, for cleanup."""
    added = []
    if "py_clob_client_v2" not in sys.modules:
        clob_mod = types.ModuleType("py_clob_client_v2")
        for name in ("ClobClient", "OrderArgsV2", "OrderType",
                     "PartialCreateOrderOptions", "OrderPayload",
                     "OrderScoringParams"):
            setattr(clob_mod, name, type(name, (), {}))
        sys.modules["py_clob_client_v2"] = clob_mod
        added.append("py_clob_client_v2")

        builder_pkg = types.ModuleType("py_clob_client_v2.order_builder")
        sys.modules["py_clob_client_v2.order_builder"] = builder_pkg
        added.append("py_clob_client_v2.order_builder")

        constants_mod = types.ModuleType("py_clob_client_v2.order_builder.constants")
        constants_mod.BUY = "BUY"
        constants_mod.SELL = "SELL"
        sys.modules["py_clob_client_v2.order_builder.constants"] = constants_mod
        added.append("py_clob_client_v2.order_builder.constants")
    return added


@pytest.fixture()
def farming_daemon():
    """Import executor/farming_daemon.py as a top-level module `farming_daemon`
    (NOT `from executor import farming_daemon`: executor/ also holds an
    unrelated executor/executor.py, so resolving the package name "executor"
    here would risk hitting that file instead). sys.path / sys.modules /
    already-imported farming_daemon are all restored on teardown."""
    path_inserted = _EXECUTOR_DIR not in sys.path
    if path_inserted:
        sys.path.insert(0, _EXECUTOR_DIR)
    stub_keys = _install_clob_stub()
    had_farming_daemon = "farming_daemon" in sys.modules

    try:
        import farming_daemon as fd
        yield fd
    finally:
        if not had_farming_daemon:
            sys.modules.pop("farming_daemon", None)
        for key in stub_keys:
            sys.modules.pop(key, None)
        if path_inserted:
            try:
                sys.path.remove(_EXECUTOR_DIR)
            except ValueError:
                pass


class _FailingClient:
    """Minimal stand-in for ClobClient whose get_open_orders() always raises."""

    def get_open_orders(self):
        raise RuntimeError("simulated CLOB API outage")


class _OkClient:
    """get_open_orders() succeeds but returns an empty book (no live orders)."""

    def get_open_orders(self):
        return []


def _fresh_state():
    return {"ids": ("bid_123", "ask_456"), "unload_id": None}


def test_reconcile_orders_sets_error_flag_on_api_failure(farming_daemon):
    """[FARM-036] get_open_orders() raising -> out['error'] is True, so the
    caller knows NOT to trust out['one_sided'] (which stays at its unchecked
    default)."""
    st = _fresh_state()
    out = farming_daemon.reconcile_orders(_FailingClient(), "tok1", st, min_size=100)
    assert out.get("error") is True
    # Default remains False -- the caller must gate on 'error', not trust this.
    assert out["one_sided"] is False


def test_reconcile_orders_no_error_flag_on_success(farming_daemon):
    """Baseline: a successful (even if empty) book read must NOT set 'error',
    so the normal latch-update path keeps working. Empty book with 2 tracked
    ids -> both legs missing -> missing_legs=True (fill-pause path), which is
    the expected/unrelated behavior here, not the FARM-036 bug."""
    st = _fresh_state()
    out = farming_daemon.reconcile_orders(_OkClient(), "tok1", st, min_size=100)
    assert not out.get("error")
    assert out["missing_legs"] is True


def test_reconcile_orders_first_tick_no_error_flag(farming_daemon):
    """st['ids'] is None (fresh restart / first tick) is a deliberate
    early-return, not an API failure -- must not set 'error' either (the
    caller already separately guards this case via ids_before_reseed)."""
    st = {"ids": None, "unload_id": None}
    out = farming_daemon.reconcile_orders(_OkClient(), "tok1", st, min_size=100)
    assert not out.get("error")
