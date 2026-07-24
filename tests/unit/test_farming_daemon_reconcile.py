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


# ─── FARM-053: per-market adaptive quote_offset_for() ────────────────────────

def test_quote_offset_for_none_max_spread_falls_back_to_constant(farming_daemon):
    assert farming_daemon.quote_offset_for(None) == farming_daemon.QUOTE_OFFSET


def test_quote_offset_for_zero_max_spread_falls_back_to_constant(farming_daemon):
    assert farming_daemon.quote_offset_for(0) == farming_daemon.QUOTE_OFFSET


def test_quote_offset_for_narrow_market_tightens_below_constant(farming_daemon):
    """[FARM-053] McConnell-like market (max_spread=3.5c): adaptive offset
    must come out below the old fixed 2c, and hit the target safety margin
    M_TARGET on the F2 metric (offset / (REQUOTE_FRAC * be_margin))."""
    off = farming_daemon.quote_offset_for(3.5)
    assert off < farming_daemon.QUOTE_OFFSET
    assert round(off, 4) == round(1.3125 / 100.0, 4)
    be_margin = 3.5 - off * 100.0
    thr = farming_daemon.REQUOTE_FRAC * be_margin
    M = (off * 100.0) / thr
    assert abs(M - farming_daemon.M_TARGET) < 1e-6


def test_quote_offset_for_wide_market_capped_at_constant(farming_daemon):
    """[FARM-053] Wide-max_spread market (5.5c): the uncapped candidate would
    be WIDER than today's fixed 2c -- must be capped there, not exceed it
    (adaptive offset only ever tightens vs the pre-FARM-053 baseline)."""
    off = farming_daemon.quote_offset_for(5.5)
    assert off == farming_daemon.QUOTE_OFFSET


def test_quote_offset_for_never_exceeds_fixed_constant(farming_daemon):
    """Sweep a range of max_spread values -- adaptive offset must never come
    out wider than the historical fixed constant, for any input."""
    for ms in (1.0, 2.0, 3.5, 4.5, 5.5, 8.0, 20.0):
        assert farming_daemon.quote_offset_for(ms) <= farming_daemon.QUOTE_OFFSET


def test_inventory_manage_flat_plan_uses_passed_offset(farming_daemon):
    """[FARM-053] inventory_manage's flat-plan bid/ask offset must come from
    the explicit `offset` parameter (the per-market st["offset"] the caller
    already computed this tick), not silently fall back to the fixed
    QUOTE_OFFSET when a caller-supplied value is available."""
    mkt = {"token": "tok1", "min_size": 200, "inv_center": 200,
           "inv_deadband": 100, "max_inv": 1000}
    plan = farming_daemon.inventory_manage(
        None, mkt, inv_shares=200, mid=0.405,
        params={"max_spread": 3.5}, offset=0.013125)
    assert plan["skew"] == "flat"
    assert plan["bid_offset"] == 0.013125
    assert plan["ask_offset"] == 0.013125


def test_inventory_manage_offset_none_falls_back_to_constant(farming_daemon):
    """No offset passed (e.g. a caller that hasn't computed it yet) -> falls
    back to the fixed QUOTE_OFFSET, matching pre-FARM-053 behavior."""
    mkt = {"token": "tok1", "min_size": 200, "inv_center": 200,
           "inv_deadband": 100, "max_inv": 1000}
    plan = farming_daemon.inventory_manage(
        None, mkt, inv_shares=200, mid=0.405,
        params={"max_spread": 3.5}, offset=None)
    assert plan["bid_offset"] == farming_daemon.QUOTE_OFFSET
    assert plan["ask_offset"] == farming_daemon.QUOTE_OFFSET


class _UnloadClient:
    """One resting SELL (the unload order) at a fixed price; get_open_orders()
    always returns it, so reconcile_orders() reaches the unload-drift branch."""

    def __init__(self, price=0.50):
        self.price = price

    def get_open_orders(self):
        return [{"id": "unload_1", "order_id": "unload_1", "side": "SELL",
                  "price": self.price, "original_size": "50", "size_matched": "0",
                  "asset_id": "tok1"}]

    def get_tick_size(self, token):
        return "0.01"


def test_reconcile_orders_unload_drift_tiny_offset_uses_tick_floor(farming_daemon, monkeypatch):
    """[FARM-053] offset=0.001 (0.1c) -> REQUOTE_FRAC*offset*100=0.04c, far
    below tick=1c, so the tick-size floor governs: drift=0.5c <= 1.0c floor
    -> unload NOT cancelled. Proves the tiny passed offset doesn't make the
    threshold collapse below the tick floor."""
    cancelled = []
    monkeypatch.setattr(farming_daemon, "cancel_quotes",
                        lambda c, ids: cancelled.append(tuple(ids or ())))
    st = {"ids": ("bid_1",), "unload_id": "unload_1"}
    farming_daemon.reconcile_orders(
        _UnloadClient(price=0.50), "tok1", st, min_size=100, mid=0.495, offset=0.001)
    assert cancelled == []


def test_reconcile_orders_unload_drift_scales_with_passed_offset(farming_daemon, monkeypatch):
    """[FARM-053] offset=0.05 (5c) -> threshold = max(REQUOTE_FRAC*0.05*100, tick)
    = max(2.0, 1.0) = 2.0c. drift=1.5c is chosen to DISCRIMINATE: it stays
    UNDER this 2.0c threshold (no cancel) but would EXCEED the threshold the
    OLD fixed QUOTE_OFFSET=0.02 would have produced (max(0.4*2c,1c)=1.0c <
    1.5c -> would cancel). If the code silently ignored the passed `offset`
    and fell back to the fixed constant, this test would see a spurious
    cancel and fail -- a drift value that triggers a cancel under BOTH
    thresholds would NOT catch that regression."""
    cancelled = []
    monkeypatch.setattr(farming_daemon, "cancel_quotes",
                        lambda c, ids: cancelled.append(tuple(ids or ())))
    st = {"ids": ("bid_1",), "unload_id": "unload_1"}
    # unload price=0.50, mid=0.485 -> drift = |0.485-0.50|*100 = 1.5c
    farming_daemon.reconcile_orders(
        _UnloadClient(price=0.50), "tok1", st, min_size=100, mid=0.485, offset=0.05)
    assert cancelled == []


# ─── FARM-053 follow-up: skewed-leg drift-safety floor (found by review) ─────
#
# Post-review finding: inventory_manage()'s skew branches pulled a leg to
# `off/2.0` ("tighter") to accelerate unload/reseed, but the main tick loop's
# drift-requote trigger measures against a threshold derived from the FLAT
# `off` (thr = REQUOTE_FRAC*(max_spread-off)), not from `tighter`. Since
# FARM-053 made `off` itself market-adaptive (tighter on narrow markets),
# off/2.0 could land BELOW that threshold -- mid could drift through the
# skewed leg's actual position before a reposition fires. Fix (reviewed by
# Opus): floor `tighter` at thr_cents + a half-tick rounding buffer, capped
# at `off` itself so the "tighter" leg is never pushed wider than flat.

_MCCONNELL_PARAMS = {"max_spread": 3.5, "tick_size": 0.01}
_MCCONNELL_OFFSET = 0.013125  # quote_offset_for(3.5) with M_TARGET=1.5, REQUOTE_FRAC=0.4


def test_inventory_manage_long_unload_floor_prevents_unsafe_tighter(farming_daemon):
    """McConnell-like market: naive off/2.0=0.0065625 would sit BELOW the
    drift-requote threshold (thr=REQUOTE_FRAC*(3.5-1.3125)=0.875c=0.00875$).
    The floor must lift ask_offset to a safe value (here: capped at `off`
    itself, since thr+buffer exceeds off on this narrow a market)."""
    mkt = {"token": "tok1", "min_size": 200, "inv_center": 200,
           "inv_deadband": 50, "max_inv": 1000}
    plan = farming_daemon.inventory_manage(
        None, mkt, inv_shares=300, mid=0.405,
        params=_MCCONNELL_PARAMS, offset=_MCCONNELL_OFFSET)
    assert plan["skew"] == "long_unload"
    thr_cents = farming_daemon.REQUOTE_FRAC * (3.5 - _MCCONNELL_OFFSET * 100.0)
    assert plan["ask_offset"] * 100.0 > thr_cents
    assert plan["ask_offset"] == pytest.approx(_MCCONNELL_OFFSET)  # floor == off here
    assert plan["ask_offset"] > _MCCONNELL_OFFSET / 2.0  # confirms the floor actually raised it above naive off/2.0
    assert plan["bid_offset"] == pytest.approx(_MCCONNELL_OFFSET * 2.0)


def test_inventory_manage_reseed_buy_floor_prevents_unsafe_tighter(farming_daemon):
    """Same floor must apply to the OTHER skew branch (reseed_buy, delta <
    -dead) -- the original review finding only mentioned long_unload; the
    bug is identical in reseed_buy and was easy to miss since it's a
    separate elif with its own `tighter = max(off/2.0, 0.005)` line."""
    mkt = {"token": "tok1", "min_size": 200, "inv_center": 200,
           "inv_deadband": 50, "max_inv": 1000}
    plan = farming_daemon.inventory_manage(
        None, mkt, inv_shares=100, mid=0.405,
        params=_MCCONNELL_PARAMS, offset=_MCCONNELL_OFFSET)
    assert plan["skew"] == "reseed_buy"
    thr_cents = farming_daemon.REQUOTE_FRAC * (3.5 - _MCCONNELL_OFFSET * 100.0)
    assert plan["bid_offset"] * 100.0 > thr_cents
    assert plan["bid_offset"] == pytest.approx(_MCCONNELL_OFFSET)


def test_inventory_manage_skew_floor_preserves_some_tightening_on_wide_market(farming_daemon):
    """Wide market (max_spread=5.5, offset capped at QUOTE_OFFSET=2c): the
    floor should NOT fully erase the unload-acceleration benefit here --
    thr+buffer (1.9c) stays below the flat offset (2c), so tighter=1.9c is
    used (narrower than flat, unlike the McConnell case where the floor
    equals `off` exactly)."""
    mkt = {"token": "tok1", "min_size": 200, "inv_center": 200,
           "inv_deadband": 50, "max_inv": 1000}
    plan = farming_daemon.inventory_manage(
        None, mkt, inv_shares=300, mid=0.405,
        params={"max_spread": 5.5, "tick_size": 0.01},
        offset=farming_daemon.QUOTE_OFFSET)
    assert plan["ask_offset"] == pytest.approx(0.019)
    assert plan["ask_offset"] < farming_daemon.QUOTE_OFFSET  # tighter than flat, benefit preserved


def test_inventory_manage_skew_floor_falls_back_to_off_half_when_max_spread_unknown(farming_daemon):
    """No max_spread available -> no basis to compute the safety floor;
    falls back to the pre-fix off/2.0 behavior (matches the pre-FARM-053
    fixed-offset era, where max_spread was always known by this point in
    practice -- this is a defensive fallback, not the expected live path)."""
    mkt = {"token": "tok1", "min_size": 200, "inv_center": 200,
           "inv_deadband": 50, "max_inv": 1000}
    plan = farming_daemon.inventory_manage(
        None, mkt, inv_shares=300, mid=0.405,
        params={"max_spread": None, "tick_size": 0.01},
        offset=farming_daemon.QUOTE_OFFSET)
    assert plan["ask_offset"] == pytest.approx(farming_daemon.QUOTE_OFFSET / 2.0)
