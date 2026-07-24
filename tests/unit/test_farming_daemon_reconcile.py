# -*- coding: utf-8 -*-
"""Unit tests for executor/farming_daemon.py internals that don't need a live
CLOB connection:

  - FARM-036: reconcile_orders() must not let a get_open_orders() API error
    masquerade as a confirmed "two-sided" book.
  - FARM-039 p.5: enter_pause() (circuit breaker / adverse-fill reaction)
    must NOT cancel the auto-unload SELL order — only the quoting legs.
    Inventory should keep draining via the resting unload order through a
    quoting pause, not stall for the whole pause window.

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


# ─── FARM-039 p.5: enter_pause() must not cancel the auto-unload order ───────

def test_enter_pause_cancels_legs_but_not_unload(farming_daemon, monkeypatch):
    """[FARM-039 p.5] Circuit-breaker / adverse-fill pause cancels the tracked
    BID/ASK legs, but the auto-unload SELL must be left resting so inventory
    keeps draining through the pause window (prior behavior cancelled it too,
    treating it as 'bait' same as the legs -- reversed per operator direction)."""
    cancelled_batches = []
    monkeypatch.setattr(farming_daemon, "cancel_quotes",
                        lambda c, ids: cancelled_batches.append(tuple(ids or ())))
    monkeypatch.setattr(farming_daemon, "notify", lambda *a, **k: None)

    st = {"ids": ("bid_1", "ask_1"), "unload_id": "unload_1", "pause_until": 0}
    mkt = {"name": "Test Market", "token": "tok1"}

    farming_daemon.enter_pause(object(), st, mkt, 60, "test reason")

    # Only ONE cancel_quotes call, and it's the legs -- unload_id was never
    # passed to cancel_quotes at all.
    assert cancelled_batches == [("bid_1", "ask_1")]
    assert st["ids"] is None
    assert st["center"] is None
    # unload_id survives the pause untouched -- still tracked for the next
    # un-paused tick's reconcile_orders() drift-discipline.
    assert st["unload_id"] == "unload_1"
    assert st["pause_until"] > 0


def test_enter_pause_no_unload_is_noop_for_unload(farming_daemon, monkeypatch):
    """No unload order pending (unload_id=None) -> nothing unload-related
    happens, and only the legs batch is cancelled -- no accidental second
    cancel_quotes call with an empty/None id."""
    cancelled_batches = []
    monkeypatch.setattr(farming_daemon, "cancel_quotes",
                        lambda c, ids: cancelled_batches.append(tuple(ids or ())))
    monkeypatch.setattr(farming_daemon, "notify", lambda *a, **k: None)

    st = {"ids": ("bid_1", "ask_1"), "unload_id": None, "pause_until": 0}
    mkt = {"name": "Test Market", "token": "tok1"}

    farming_daemon.enter_pause(object(), st, mkt, 60, "test reason")

    assert cancelled_batches == [("bid_1", "ask_1")]
    assert st["unload_id"] is None


# ─── FARM-042: _alerts pruning + halted recovery latch ───────────────────────

def test_save_state_file_prunes_alerts_for_rotated_out_tokens(
    farming_daemon, monkeypatch, tmp_path
):
    """[FARM-042] A token no longer in MARKETS (rotated out) must not keep its
    alert-latch keys in _alerts forever -- that's exactly how phantom entries
    accumulate and inflate the bot's /status 'stale' counter without bound."""
    state_file = tmp_path / "farming_state.json"
    monkeypatch.setattr(farming_daemon, "STATE_FILE", str(state_file))
    monkeypatch.setattr(farming_daemon, "MARKETS", [{"token": "current_tok"}])
    monkeypatch.setattr(farming_daemon, "_alert_state", {
        "halted:current_tok": True,
        "halted:rotated_out_tok": True,
        "auto_unload:rotated_out_tok": True,
    })

    farming_daemon.save_state_file({})

    import json
    with open(state_file) as f:
        saved = json.load(f)
    assert saved["_alerts"] == {"halted:current_tok": True}
    # In-memory latch is pruned too, not just what's written to disk.
    assert farming_daemon._alert_state == {"halted:current_tok": True}


def test_save_state_file_keeps_colon_free_keys(farming_daemon, monkeypatch, tmp_path):
    """Defensive: a key with no ':' (not the current halted/pause/auto_unload/
    balance_reject naming convention) is kept, not treated as phantom -- the
    prune only removes keys whose token suffix is identifiably gone."""
    state_file = tmp_path / "farming_state.json"
    monkeypatch.setattr(farming_daemon, "STATE_FILE", str(state_file))
    monkeypatch.setattr(farming_daemon, "MARKETS", [{"token": "current_tok"}])
    monkeypatch.setattr(farming_daemon, "_alert_state", {"no_colon_key": True})

    farming_daemon.save_state_file({})

    import json
    with open(state_file) as f:
        saved = json.load(f)
    assert saved["_alerts"] == {"no_colon_key": True}


def test_edge_notify_halted_recovery_fires_on_true_to_false(farming_daemon):
    """[FARM-042] The recovery call added at the non-halted fall-through
    (mirrors the daemon's own manual-clear-then-restart path: st['halted']
    goes True -> False only via an operator JSON edit + restart) must produce
    a recovery notification and flip the latch, exactly like any other
    edge_notify onset/recovery pair."""
    sent = []
    farming_daemon._alert_state.clear()
    farming_daemon._alert_state["halted:tokX"] = True
    orig_notify = farming_daemon.notify
    farming_daemon.notify = lambda msg: sent.append(msg)
    try:
        farming_daemon.edge_notify(
            "halted:tokX", False, "", "\U0001F7E2 HALT снят (Test)", cooldown=0)
    finally:
        farming_daemon.notify = orig_notify

    assert sent == ["\U0001F7E2 HALT снят (Test)"]
    assert farming_daemon._alert_state["halted:tokX"] is False


def test_edge_notify_halted_recovery_silent_when_already_clear(farming_daemon):
    """Calling the same recovery edge every non-halted tick must stay silent
    once already recovered (prev is False/None) -- it's meant to be cheap and
    idempotent, not a per-tick spam source."""
    sent = []
    farming_daemon._alert_state.clear()
    farming_daemon._alert_state["halted:tokY"] = False
    orig_notify = farming_daemon.notify
    farming_daemon.notify = lambda msg: sent.append(msg)
    try:
        farming_daemon.edge_notify("halted:tokY", False, "", "recovered", cooldown=0)
    finally:
        farming_daemon.notify = orig_notify

    assert sent == []


# ─── FARM-052: get_open_orders() list staleness -> get_order() confirmation ──

class _OrderStatusClient:
    """get_open_orders() returns an empty book (both tracked ids absent from
    the list); get_order(id) returns a canned per-id status from `statuses`
    (dict oid -> status string, or oid -> None to simulate 'not found')."""

    def __init__(self, statuses):
        self.statuses = statuses
        self.queried = []

    def get_open_orders(self):
        return []

    def get_order(self, order_id):
        self.queried.append(order_id)
        status = self.statuses.get(order_id)
        if status is None:
            return None
        return {"status": status}


def test_order_is_live_true_for_live_status(farming_daemon):
    c = _OrderStatusClient({"bid_123": "live"})
    assert farming_daemon.order_is_live(c, "bid_123") is True


def test_order_is_live_false_for_terminal_status(farming_daemon):
    c = _OrderStatusClient({"bid_123": "matched"})
    assert farming_daemon.order_is_live(c, "bid_123") is False


def test_order_is_live_false_when_not_found(farming_daemon):
    c = _OrderStatusClient({"bid_123": None})
    assert farming_daemon.order_is_live(c, "bid_123") is False


def test_order_is_live_none_on_lookup_error(farming_daemon):
    class _Raising:
        def get_order(self, order_id):
            raise RuntimeError("simulated CLOB API outage")
    assert farming_daemon.order_is_live(_Raising(), "bid_123") is None


def test_reconcile_stale_list_snapshot_does_not_pause(farming_daemon):
    """[FARM-052] Both tracked legs are absent from get_open_orders() (empty
    list), matching the 24.07 McConnell incident pattern (a just-posted order
    absent from the very next list call) -- but get_order() confirms both are
    still status='live'. Must NOT trigger missing_legs (no false pause)."""
    st = _fresh_state()
    c = _OrderStatusClient({"bid_123": "live", "ask_456": "live"})
    out = farming_daemon.reconcile_orders(c, "tok1", st, min_size=100)
    assert out["missing_legs"] is False
    assert sorted(c.queried) == ["ask_456", "bid_123"]


def test_reconcile_confirmed_gone_still_pauses(farming_daemon):
    """[FARM-052] Both tracked legs absent from the list AND get_order()
    confirms a terminal status (genuinely filled/cancelled) -- missing_legs
    must still fire, same as pre-FARM-052 behavior for a real vanish."""
    st = _fresh_state()
    c = _OrderStatusClient({"bid_123": "matched", "ask_456": "canceled"})
    out = farming_daemon.reconcile_orders(c, "tok1", st, min_size=100)
    assert out["missing_legs"] is True


def test_reconcile_mixed_stale_and_gone_pauses_only_for_confirmed(farming_daemon, monkeypatch):
    """[FARM-052] One leg is a stale list read (still live), the other is
    genuinely gone -- pause still fires (real vanish present), but only the
    confirmed-gone id reaches the pause log, not the stale one."""
    logged = []
    monkeypatch.setattr(farming_daemon, "log", lambda msg: logged.append(msg))
    st = _fresh_state()
    c = _OrderStatusClient({"bid_123": "live", "ask_456": "matched"})
    out = farming_daemon.reconcile_orders(c, "tok1", st, min_size=100)
    assert out["missing_legs"] is True
    pause_lines = [m for m in logged if "tracked leg(s) missing" in m]
    assert len(pause_lines) == 1
    assert "ask_456" in pause_lines[0]
    assert "bid_123" not in pause_lines[0]
    stale_lines = [m for m in logged if "stale list" in m]
    assert len(stale_lines) == 1
    assert "bid_123" in stale_lines[0]
