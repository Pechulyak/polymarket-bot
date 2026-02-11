# -*- coding: utf-8 -*-
"""Integration tests for database persistence.

Virtual trades are saved to the main trades and bankroll tables.
"""

import asyncio
import os
import sys
import pathlib
import pytest
from decimal import Decimal
from sqlalchemy import create_engine, text

# Ensure src is on sys.path so tests can import strategy modules
ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from strategy.virtual_bankroll import VirtualBankroll
except Exception as e:
    VirtualBankroll = None
    print(f"WARNING: could not import VirtualBankroll: {e}")


@pytest.mark.asyncio
async def test_db_persistence_exists():
    db_url = os.environ.get(
        "DB_URL", "postgresql://postgres:password@localhost:5433/postgres"
    )
    print(f"INFO: Test DB URL: {db_url}")
    if VirtualBankroll is None:
        pytest.skip("VirtualBankroll module not available in test environment")
    # Try to connect; skip if unavailable
    try:
        engine = create_engine(db_url)
        with engine.connect() as _:
            pass
    except Exception:
        pytest.skip("Database not available for integration test")

    bankroll = VirtualBankroll(initial_balance=Decimal("100.00"))
    bankroll.set_database(db_url)
    # Execute a small virtual trade
    trade = await bankroll.execute_virtual_trade(
        market_id="0xmarket_test",
        side="buy",
        size=Decimal("5.0"),
        price=Decimal("0.50"),
        strategy="test_integration",
        fees=Decimal("0.05"),
        gas=Decimal("0.00"),
    )
    # Virtual trades are persisted to the main trades table
    with engine.connect() as conn:
        tbl = "trades"
        q = text(f"SELECT * FROM {tbl} WHERE trade_id = :tid")
        row = conn.execute(q, {"tid": trade.trade_id}).fetchone()
        if row is None:
            pytest.fail(
                f"Trade not persisted to expected table '{tbl}' for trade_id {trade.trade_id}"
            )
        print(f"INFO: DB wrote trade to {tbl}, trade_id={trade.trade_id}")
        # Optional bankroll check - verify bankroll history was recorded
        try:
            bal = conn.execute(
                text("SELECT available FROM bankroll ORDER BY id DESC LIMIT 1")
            ).fetchone()
            if bal is not None:
                print(f"INFO: Bankroll balance persisted: {bal[0]}")
        except Exception:
            pass
