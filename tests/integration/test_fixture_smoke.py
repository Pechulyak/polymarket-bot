# -*- coding: utf-8 -*-
"""Smoke test for test_engine fixture from conftest.py.

Verifies:
- Container starts, schema applies cleanly
- Engine connects, all expected tables exist
- TRUNCATE fixture works between tests
"""
import pytest
from sqlalchemy import text


def test_engine_connects(test_engine):
    """Engine can execute basic query."""
    with test_engine.connect() as conn:
        result = conn.execute(text("SELECT 1 AS one"))
        assert result.scalar() == 1


def test_required_tables_exist(test_engine):
    """All tables _close_roundtrips depends on are present."""
    with test_engine.connect() as conn:
        result = conn.execute(text("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public' 
              AND tablename IN ('whale_trade_roundtrips', 'whale_trades', 'whales')
            ORDER BY tablename
        """))
        tables = [row[0] for row in result]
    assert tables == ['whale_trade_roundtrips', 'whale_trades', 'whales'], \
        f"Expected 3 core tables, got: {tables}"


def test_whale_trade_roundtrips_has_close_columns(test_engine):
    """close_* columns and matching_method/confidence/pnl_status exist."""
    with test_engine.connect() as conn:
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'whale_trade_roundtrips'
              AND column_name IN (
                  'close_trade_id', 'close_side', 'close_size_usd', 'fees_usd',
                  'matching_method', 'matching_confidence', 'pnl_status',
                  'position_key', 'close_type', 'opened_at', 'closed_at',
                  'is_legacy_close'
              )
            ORDER BY column_name
        """))
        columns = [row[0] for row in result]
    required = sorted([
        'close_trade_id', 'close_side', 'close_size_usd', 'fees_usd',
        'matching_method', 'matching_confidence', 'pnl_status',
        'position_key', 'close_type', 'opened_at', 'closed_at',
        'is_legacy_close',
    ])
    assert columns == required, f"missing columns. expected {required}, got {columns}"


def test_clean_tables_truncates(test_engine, clean_tables):
    """clean_tables fixture truncates whale_trade_roundtrips."""
    # Insert a row
    with test_engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO whales (wallet_address, source_new) 
            VALUES ('0xtest', 'test')
        """))
        conn.commit()
        count = conn.execute(text("SELECT COUNT(*) FROM whales")).scalar()
    assert count == 1


def test_clean_tables_isolation(test_engine, clean_tables):
    """Second test sees zero rows — proves clean_tables ran again."""
    with test_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM whales")).scalar()
    assert count == 0, "clean_tables fixture did not isolate from previous test"