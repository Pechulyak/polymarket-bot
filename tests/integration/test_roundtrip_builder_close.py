# -*- coding: utf-8 -*-
"""Integration tests for RoundtripBuilder._close_roundtrips (TRD-443).

Tests use the real ephemeral postgres fixture from conftest.py.
Each test seeds data via _helpers, runs run_close_positions(), and asserts
on the resulting database state.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from strategy.roundtrip_builder import RoundtripBuilder
from tests.integration._helpers import (
    insert_whale,
    insert_open_roundtrip,
    insert_whale_trade,
    get_roundtrip,
)


def _make_builder(test_engine):
    """Instantiate RoundtripBuilder with test engine injected.

    Bypasses the default __init__ behavior that reads DATABASE_URL from env.
    We override _engine to point at the test container.
    """
    builder = RoundtripBuilder.__new__(RoundtripBuilder)
    builder._engine = test_engine
    return builder


def test_t1_exact_match_closes_roundtrip(test_engine, clean_tables):
    """T1: OPEN + matching SELL → CLOSED with DIRECT_SELL/HIGH/EXACT.

    Setup: whale, OPEN roundtrip (Yes, $100 @ 0.50), SELL trade (Yes, $80 @ 0.60, traded_at > opened_at).
    Expected:
        - status = 'CLOSED'
        - close_type = 'SELL'
        - matching_method = 'DIRECT_SELL'
        - matching_confidence = 'HIGH'
        - pnl_status = 'EXACT'
        - close_trade_id = sell.id
        - close_side = 'sell'
        - close_size_usd = 80.00
        - fees_usd = 0
        - gross_pnl_usd = (0.60 - 0.50) * 80 = 8.00
    """
    wallet = "0xtest_t1"
    market = "0xmarket_t1"
    outcome = "Yes"
    opened_at = datetime.utcnow() - timedelta(hours=2)
    traded_at = datetime.utcnow() - timedelta(hours=1)

    # Seed
    whale_id = insert_whale(test_engine, wallet_address=wallet)
    roundtrip_id = insert_open_roundtrip(
        test_engine,
        whale_id=whale_id,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        open_price=Decimal("0.50"),
        open_size_usd=Decimal("100.00"),
        opened_at=opened_at,
    )
    sell_trade_id = insert_whale_trade(
        test_engine,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        side="sell",
        price=Decimal("0.60"),
        size_usd=Decimal("80.00"),
        traded_at=traded_at,
    )

    # Act
    builder = _make_builder(test_engine)
    result = builder.run_close_positions()

    # Assert: return structure
    assert result["sell_groups"] == 1, f"expected 1 sell group, got {result}"
    assert result["closed"] == 1, f"expected 1 closed, got {result}"
    assert result["closed_direct"] == 1, f"expected direct=1, got {result}"
    assert result["closed_fuzzy"] == 0, f"expected fuzzy=0, got {result}"
    assert result["skipped"] == 0, f"expected skipped=0, got {result}"

    # Assert: roundtrip state in DB
    rt = get_roundtrip(test_engine, roundtrip_id)
    assert rt["status"] == "CLOSED", f"status: {rt['status']}"
    assert rt["close_type"] == "SELL", f"close_type: {rt['close_type']}"
    assert rt["matching_method"] == "DIRECT_SELL", f"matching_method: {rt['matching_method']}"
    assert rt["matching_confidence"] == "HIGH", f"matching_confidence: {rt['matching_confidence']}"
    assert rt["pnl_status"] == "EXACT", f"pnl_status: {rt['pnl_status']}"
    assert rt["close_trade_id"] == sell_trade_id, f"close_trade_id: {rt['close_trade_id']} vs {sell_trade_id}"
    assert rt["close_side"] == "sell", f"close_side: {rt['close_side']}"
    assert float(rt["close_size_usd"]) == 80.00, f"close_size_usd: {rt['close_size_usd']}"
    assert float(rt["fees_usd"]) == 0.0, f"fees_usd: {rt['fees_usd']}"
    # P&L: (0.60 - 0.50) * 80 = 8.00
    assert float(rt["gross_pnl_usd"]) == pytest.approx(8.00, abs=0.01), \
        f"gross_pnl_usd: {rt['gross_pnl_usd']}"


def test_t2_no_match_skips(test_engine, clean_tables):
    """T2: OPEN with no matching SELL → remains OPEN, skipped_count=1.

    Setup: whale, OPEN roundtrip (Yes), NO sell trades at all.
    Expected:
        - sell_groups = 0 (no SELL events found)
        - closed = 0
        - skipped = 0 (nothing to attempt)
        - roundtrip remains status='OPEN'

    Note: skipped_count in _close_roundtrips refers to processed sell_groups
    that didn't find a match. If sell_groups=0, skipped=0 too.
    """
    wallet = "0xtest_t2"
    market = "0xmarket_t2"
    opened_at = datetime.utcnow() - timedelta(hours=2)

    whale_id = insert_whale(test_engine, wallet_address=wallet)
    roundtrip_id = insert_open_roundtrip(
        test_engine,
        whale_id=whale_id,
        wallet_address=wallet,
        market_id=market,
        outcome="Yes",
        opened_at=opened_at,
    )
    # NO insert_whale_trade — no sell events

    builder = _make_builder(test_engine)
    result = builder.run_close_positions()

    assert result["sell_groups"] == 0, f"expected 0 sell groups, got {result}"
    assert result["closed"] == 0
    assert result["skipped"] == 0

    rt = get_roundtrip(test_engine, roundtrip_id)
    assert rt["status"] == "OPEN", f"roundtrip should remain OPEN, got {rt['status']}"
    assert rt["close_type"] is None, f"close_type should be NULL, got {rt['close_type']}"


def test_t3_fuzzy_match_via_outcome_keys(test_engine, clean_tables):
    """T3: OPEN with non-standard position_key → exact fails, fuzzy succeeds.

    Models the scenario where position_key in DB doesn't match the key computed
    from (wallet, market, outcome) by _fetch_and_group_sell_trades. This is the
    only case where fuzzy fallback adds value (per §16.2 C2.b spec).

    Setup:
        - whale, OPEN roundtrip with intentionally MISMATCHED position_key
          (e.g. position_key='legacy_format_key', but wallet/market/outcome match)
        - SELL trade with matching wallet/market/outcome
    Expected:
        - exact query (WHERE position_key=:position_key) finds nothing
        - fuzzy query (WHERE wallet+market+outcome) finds the roundtrip
        - matching_method = 'FUZZY_FLIP', matching_confidence = 'LOW', pnl_status = 'ESTIMATED'
    """
    wallet = "0xtest_t3"
    market = "0xmarket_t3"
    outcome = "Yes"
    opened_at = datetime.utcnow() - timedelta(hours=2)
    traded_at = datetime.utcnow() - timedelta(hours=1)

    whale_id = insert_whale(test_engine, wallet_address=wallet)
    # INTENTIONALLY mismatched position_key — what _fetch_and_group_sell_trades
    # will compute is f"{wallet}:{market}:{outcome}", but we store a different value
    mismatched_key = "legacy_format_key_t3"
    roundtrip_id = insert_open_roundtrip(
        test_engine,
        whale_id=whale_id,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        opened_at=opened_at,
        position_key=mismatched_key,  # override default
    )
    sell_trade_id = insert_whale_trade(
        test_engine,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        side="sell",
        price=Decimal("0.55"),
        size_usd=Decimal("90.00"),
        traded_at=traded_at,
    )

    builder = _make_builder(test_engine)
    result = builder.run_close_positions()

    assert result["sell_groups"] == 1, f"expected 1 sell group, got {result}"
    assert result["closed"] == 1, f"expected 1 closed, got {result}"
    assert result["closed_direct"] == 0, f"expected direct=0 (fuzzy path), got {result}"
    assert result["closed_fuzzy"] == 1, f"expected fuzzy=1, got {result}"
    assert result["skipped"] == 0

    rt = get_roundtrip(test_engine, roundtrip_id)
    assert rt["status"] == "CLOSED"
    assert rt["close_type"] == "SELL"
    assert rt["matching_method"] == "FUZZY_FLIP", f"matching_method: {rt['matching_method']}"
    assert rt["matching_confidence"] == "LOW", f"matching_confidence: {rt['matching_confidence']}"
    assert rt["pnl_status"] == "ESTIMATED", f"pnl_status: {rt['pnl_status']}"
    assert rt["close_trade_id"] == sell_trade_id


def test_close_skipped_when_sell_before_open(test_engine, clean_tables):
    """T4a: SELL with traded_at < opened_at must NOT close roundtrip (RF-001 temporal filter).

    Setup: whale, OPEN roundtrip with fixed opened_at, one SELL whale_trade
           with traded_at 1 hour BEFORE opened_at, same outcome.
    Expected:
        - roundtrip remains status='OPEN'
        - close_trade_id IS NULL, closed_at IS NULL, matching_method IS NULL
        - result: closed==0, closed_direct==0, closed_fuzzy==0, skipped>=1
    """
    wallet = "0xtest_t4a"
    market = "0xmarket_t4a"
    outcome = "Yes"
    opened_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=None)  # fixed, no tz
    # SELL 1 hour BEFORE opened_at
    traded_at = opened_at - timedelta(hours=1)

    whale_id = insert_whale(test_engine, wallet_address=wallet)
    roundtrip_id = insert_open_roundtrip(
        test_engine,
        whale_id=whale_id,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        opened_at=opened_at,
    )
    insert_whale_trade(
        test_engine,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        side="sell",
        price=Decimal("0.60"),
        size_usd=Decimal("80.00"),
        traded_at=traded_at,
    )

    builder = _make_builder(test_engine)
    result = builder.run_close_positions()

    assert result["closed"] == 0, f"expected 0 closed, got {result}"
    assert result["closed_direct"] == 0, f"expected 0 direct, got {result}"
    assert result["closed_fuzzy"] == 0, f"expected 0 fuzzy, got {result}"
    assert result["skipped"] >= 1, f"expected skipped>=1, got {result}"

    rt = get_roundtrip(test_engine, roundtrip_id)
    assert rt["status"] == "OPEN", f"roundtrip should remain OPEN, got {rt['status']}"
    assert rt["close_trade_id"] is None, f"close_trade_id should be NULL, got {rt['close_trade_id']}"
    assert rt["closed_at"] is None, f"closed_at should be NULL, got {rt['closed_at']}"
    assert rt["matching_method"] is None, f"matching_method should be NULL, got {rt['matching_method']}"


def test_close_skipped_when_sell_equals_open(test_engine, clean_tables):
    """T4b: SELL with traded_at == opened_at must NOT close roundtrip (strict > required).

    Same as T4a but traded_at exactly equals opened_at (boundary case).
    Expected: identical to T4a — roundtrip OPEN, no close fields set.
    """
    wallet = "0xtest_t4b"
    market = "0xmarket_t4b"
    outcome = "Yes"
    opened_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=None)  # fixed
    # SELL exactly at opened_at (not strictly after)
    traded_at = opened_at

    whale_id = insert_whale(test_engine, wallet_address=wallet)
    roundtrip_id = insert_open_roundtrip(
        test_engine,
        whale_id=whale_id,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        opened_at=opened_at,
    )
    insert_whale_trade(
        test_engine,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        side="sell",
        price=Decimal("0.60"),
        size_usd=Decimal("80.00"),
        traded_at=traded_at,
    )

    builder = _make_builder(test_engine)
    result = builder.run_close_positions()

    assert result["closed"] == 0, f"expected 0 closed, got {result}"
    assert result["closed_direct"] == 0, f"expected 0 direct, got {result}"
    assert result["closed_fuzzy"] == 0, f"expected 0 fuzzy, got {result}"
    assert result["skipped"] >= 1, f"expected skipped>=1, got {result}"

    rt = get_roundtrip(test_engine, roundtrip_id)
    assert rt["status"] == "OPEN", f"roundtrip should remain OPEN, got {rt['status']}"
    assert rt["close_trade_id"] is None, f"close_trade_id should be NULL, got {rt['close_trade_id']}"
    assert rt["closed_at"] is None, f"closed_at should be NULL, got {rt['closed_at']}"
    assert rt["matching_method"] is None, f"matching_method should be NULL, got {rt['matching_method']}"


def test_close_picks_latest_sell_by_time_not_id(test_engine, clean_tables):
    """T5: Multiple SELLs for same roundtrip — winner is latest by traded_at, not latest by id (RF-003).

    Inverse pattern: id and traded_at point to DIFFERENT rows.
    - SELL_LATE (first insert): traded_at = opened_at + 2 hours (later time), gets LOWER id
    - SELL_EARLY (second insert): traded_at = opened_at + 1 hour (earlier time), gets HIGHER id

    Sanity: sell_early_id > sell_late_id AND traded_at_late > traded_at_early
    This creates a real tie-breaker case:
        - ORDER BY id DESC would pick SELL_EARLY (higher id, earlier time)
        - ORDER BY traded_at DESC would pick SELL_LATE (lower id, later time)
    The code uses ROW_NUMBER() OVER (ORDER BY wt.traded_at DESC, wt.id DESC), so SELL_LATE must win.

    Expected:
        - roundtrip status='CLOSED'
        - close_trade_id == SELL_LATE.id (the one with later traded_at despite lower id)
        - matching_method='DIRECT_SELL', matching_confidence='HIGH', pnl_status='EXACT'
        - result: closed_direct >= 1
    """
    wallet = "0xtest_t5"
    market = "0xmarket_t5"
    outcome = "Yes"
    opened_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=None)

    # SELL_LATE: later traded_at, inserted FIRST → gets lower id
    traded_at_late = opened_at + timedelta(hours=2)
    # SELL_EARLY: earlier traded_at, inserted SECOND → gets higher id
    traded_at_early = opened_at + timedelta(hours=1)

    whale_id = insert_whale(test_engine, wallet_address=wallet)
    roundtrip_id = insert_open_roundtrip(
        test_engine,
        whale_id=whale_id,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        opened_at=opened_at,
    )

    # Insert LATER SELL first (gets lower id, later traded_at)
    sell_late_id = insert_whale_trade(
        test_engine,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        side="sell",
        price=Decimal("0.65"),
        size_usd=Decimal("60.00"),
        traded_at=traded_at_late,
    )
    # Insert EARLIER SELL second (gets higher id, earlier traded_at)
    sell_early_id = insert_whale_trade(
        test_engine,
        wallet_address=wallet,
        market_id=market,
        outcome=outcome,
        side="sell",
        price=Decimal("0.60"),
        size_usd=Decimal("80.00"),
        traded_at=traded_at_early,
    )

    # SANITY: inverse pattern must hold
    assert sell_early_id > sell_late_id, \
        f"sanity FAIL: sell_early_id={sell_early_id} should be > sell_late_id={sell_late_id}"
    assert traded_at_late > traded_at_early, \
        f"sanity FAIL: traded_at_late={traded_at_late} should be > traded_at_early={traded_at_early}"

    builder = _make_builder(test_engine)
    result = builder.run_close_positions()

    assert result["closed"] == 1, f"expected 1 closed, got {result}"
    assert result["closed_direct"] >= 1, f"expected closed_direct>=1, got {result}"
    assert result["skipped"] == 0, f"expected skipped=0, got {result}"

    rt = get_roundtrip(test_engine, roundtrip_id)
    assert rt["status"] == "CLOSED", f"status: {rt['status']}"
    assert rt["matching_method"] == "DIRECT_SELL", f"matching_method: {rt['matching_method']}"
    assert rt["matching_confidence"] == "HIGH", f"matching_confidence: {rt['matching_confidence']}"
    assert rt["pnl_status"] == "EXACT", f"pnl_status: {rt['pnl_status']}"
    # close_trade_id should be SELL_LATE (later traded_at despite having LOWER id)
    assert rt["close_trade_id"] == sell_late_id, \
        f"close_trade_id={rt['close_trade_id']} should be sell_late_id={sell_late_id} (latest by traded_at)"


def test_close_skipped_when_open_outcome_is_null(test_engine, clean_tables):
    """T6: OPEN roundtrip with outcome=NULL cannot be matched by SELL with concrete outcome.

    Hypothesis: fuzzy WHERE rt.outcome = :outcome uses NULL semantics.
    SQL: NULL = 'Yes' returns NULL (not TRUE). So fuzzy won't match.
    Exact match: position_key contains 'unknown' (helper formula for NULL outcome),
    SELL with outcome='Yes' generates different position_key — no match.

    Setup:
        - whale, OPEN roundtrip with outcome=None (position_key becomes 'wallet:market:unknown')
        - SELL whale_trade with outcome='Yes', traded_at > opened_at

    Expected:
        - roundtrip remains status='OPEN'
        - close_trade_id IS NULL, closed_at IS NULL, matching_method IS NULL
        - result: closed==0, closed_direct==0, closed_fuzzy==0, skipped>=1
    """
    wallet = "0xtest_t6"
    market = "0xmarket_t6"
    opened_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=None)
    traded_at = opened_at + timedelta(hours=1)  # valid SELL after open

    whale_id = insert_whale(test_engine, wallet_address=wallet)
    roundtrip_id = insert_open_roundtrip(
        test_engine,
        whale_id=whale_id,
        wallet_address=wallet,
        market_id=market,
        outcome=None,  # NULL outcome
        opened_at=opened_at,
        # position_key will be f"{wallet}:{market}:unknown" per helper formula
    )
    sell_trade_id = insert_whale_trade(
        test_engine,
        wallet_address=wallet,
        market_id=market,
        outcome="Yes",  # concrete outcome, NOT NULL
        side="sell",
        price=Decimal("0.60"),
        size_usd=Decimal("80.00"),
        traded_at=traded_at,
    )

    builder = _make_builder(test_engine)
    result = builder.run_close_positions()

    assert result["closed"] == 0, f"expected 0 closed, got {result}"
    assert result["closed_direct"] == 0, f"expected 0 direct, got {result}"
    assert result["closed_fuzzy"] == 0, f"expected 0 fuzzy, got {result}"
    assert result["skipped"] >= 1, f"expected skipped>=1, got {result}"

    rt = get_roundtrip(test_engine, roundtrip_id)
    assert rt["status"] == "OPEN", f"roundtrip should remain OPEN, got {rt['status']}"
    assert rt["close_trade_id"] is None, f"close_trade_id should be NULL, got {rt['close_trade_id']}"
    assert rt["closed_at"] is None, f"closed_at should be NULL, got {rt['closed_at']}"
    assert rt["matching_method"] is None, f"matching_method should be NULL, got {rt['matching_method']}"