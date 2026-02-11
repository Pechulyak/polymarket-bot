# -*- coding: utf-8 -*-
"""Alternative elementary DB write test via the public API path (VirtualBankroll).

This test uses the code path that writes to the existing trades table (or
virtual_trades if present) via VirtualBankroll.execute_virtual_trade, to verify
that the integration path actually persists data to the database.
"""

import os
import uuid
import asyncio
import pytest
from decimal import Decimal
from sqlalchemy import create_engine, text

try:
    from strategy.virtual_bankroll import VirtualBankroll
except Exception:
    VirtualBankroll = None


def _get_db_engine():
    db_url = os.environ.get(
        "DB_URL", "postgresql://postgres:password@localhost:5433/polymarket_test"
    )
    return create_engine(db_url), db_url


@pytest.mark.asyncio
async def test_api_write_trade_persists():
    if VirtualBankroll is None:
        pytest.skip("VirtualBankroll module not available in test env")
    engine, db_url = _get_db_engine()
    bankroll = VirtualBankroll(initial_balance=Decimal("100.00"))
    bankroll.set_database(db_url)
    # Perform a small virtual trade
    trade = await bankroll.execute_virtual_trade(
        market_id="0xmarket_api",
        side="buy",
        size=Decimal("2.0"),
        price=Decimal("0.50"),
        strategy="test_api_write",
        fees=Decimal("0.01"),
        gas=Decimal("0.00"),
    )

    # Determine which table to query
    with engine.connect() as conn:
        res = conn.execute(text("SELECT to_regclass('public.virtual_trades')"))
        vt_table = res.scalar()
        table = "virtual_trades" if vt_table else "trades"
        row = conn.execute(
            text(f"SELECT * FROM {table} WHERE trade_id = :tid"),
            {"tid": trade.trade_id},
        ).fetchone()
        assert row is not None
        print(f"INFO: API write persisted trade_id={trade.trade_id} into {table}")
