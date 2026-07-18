# -*- coding: utf-8 -*-
"""Unit tests for the SELL gate in process_one (LIVE-009).

The live executor is BUY-only; a SELL intent would be mis-executed as a
wrong-direction BUY. process_one must block any non-BUY signal before an
intent row is inserted into live_orders. Runs on both LISTEN and sweep paths
because the gate lives inside process_one itself.

psycopg2 access is fully mocked via patching the module-level helpers.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import scripts.copy_paper_to_live as m


def _trade(side: str) -> dict:
    return {
        "id": 999,
        "whale_address": "0xabc",
        "market_id": "0xmarket",
        "market_title": "T",
        "outcome": "Yes",
        "side": side,
        "kelly_size": 5.0,
        "price": 0.6,
        "tx_hash": "0xtx",
        "created_at": datetime(2026, 7, 18, 12, 0, 0),
        "token_id": "123456",
        "copy_status": "live",
    }


def _run(side: str, dup: bool = False):
    """Run process_one for a given side, returning the insert_live_order mock."""
    conn = MagicMock()
    with patch.object(m, "get_kill_switch", return_value=True), \
         patch.object(m, "get_paper_trade", return_value=_trade(side)), \
         patch.object(m, "has_live_intent_for_position", return_value=dup) as dup_mock, \
         patch.object(m, "insert_live_order", return_value=True) as insert_mock:
        m.process_one(conn, 999)
    return insert_mock, dup_mock


def test_sell_blocked_no_intent():
    insert_mock, dup_mock = _run("sell")
    insert_mock.assert_not_called()
    # gate returns before the dedup check
    dup_mock.assert_not_called()


def test_sell_uppercase_blocked():
    insert_mock, _ = _run("SELL")
    insert_mock.assert_not_called()


def test_buy_passes_to_insert():
    insert_mock, _ = _run("buy")
    insert_mock.assert_called_once()


def test_buy_uppercase_passes():
    insert_mock, _ = _run("BUY")
    insert_mock.assert_called_once()
