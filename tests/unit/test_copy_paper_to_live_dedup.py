# -*- coding: utf-8 -*-
"""Unit tests for has_live_intent_for_position (LIVE-008).

Mocks the psycopg2 cursor to verify the dedup query is parameterized
correctly and the EXISTS result is surfaced as-is, without needing a live
Postgres schema for live_orders/paper_trades.
"""

from datetime import datetime
from unittest.mock import MagicMock

from scripts.copy_paper_to_live import (
    LIVE_ORDER_DEDUP_WINDOW_HOURS,
    has_live_intent_for_position,
)

TRADE = {
    "id": 14406,
    "whale_address": "0x3da89a55cdd4b5c69f80e5cd3ef1782a3e0480c3",
    "market_id": "0x86151b3bf91d33bd9de1f5c4fd8db28a97723b8cb131af7ebb800d06118248fb",
    "outcome": "Yes",
    "side": "buy",
    "price": 0.6,
    "created_at": datetime(2026, 7, 17, 18, 27, 24),
}


def _mock_conn(exists_result: bool):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (exists_result,)
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_returns_true_when_duplicate_exists():
    conn, _ = _mock_conn(True)
    assert has_live_intent_for_position(conn, TRADE) is True


def test_returns_false_when_no_duplicate():
    conn, _ = _mock_conn(False)
    assert has_live_intent_for_position(conn, TRADE) is False


def test_query_params_match_trade_fields():
    conn, cursor = _mock_conn(False)
    has_live_intent_for_position(conn, TRADE)

    _, params = cursor.execute.call_args[0]
    assert params["whale_address"] == TRADE["whale_address"]
    assert params["market_id"] == TRADE["market_id"]
    assert params["outcome"] == TRADE["outcome"]
    assert params["side"] == TRADE["side"]
    assert params["price"] == TRADE["price"]
    assert params["trade_id"] == TRADE["id"]
    assert params["created_at"] == TRADE["created_at"]
    assert params["window_hours"] == LIVE_ORDER_DEDUP_WINDOW_HOURS


def test_excludes_self_by_trade_id():
    """The query must exclude the row's own id, or it would always match itself."""
    conn, cursor = _mock_conn(False)
    has_live_intent_for_position(conn, TRADE)

    query, params = cursor.execute.call_args[0]
    assert "pt2.id != %(trade_id)s" in query
    assert params["trade_id"] == TRADE["id"]


def test_excludes_failed_and_rejected_statuses():
    conn, cursor = _mock_conn(False)
    has_live_intent_for_position(conn, TRADE)

    query, _ = cursor.execute.call_args[0]
    assert "lo.status NOT IN ('failed', 'rejected')" in query


def test_commits_after_query():
    conn, _ = _mock_conn(False)
    has_live_intent_for_position(conn, TRADE)
    conn.commit.assert_called_once()
