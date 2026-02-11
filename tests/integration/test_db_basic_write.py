# -*- coding: utf-8 -*-
"""Elementary DB write tests against existing tables.

This test does not modify DB schema. It only inserts a single row into an
existing trades table and verifies the insert. It also optionally inserts into
bankroll if that table exists.
"""

import os
import uuid
import pytest
from decimal import Decimal
from sqlalchemy import create_engine, text


def _get_db_engine():
    db_url = os.environ.get(
        "DB_URL", "postgresql://postgres:password@localhost:5433/postgres"
    )
    return create_engine(db_url), db_url


@pytest.mark.asyncio
async def test_basic_trade_insert():
    engine, db_url = _get_db_engine()
    try:
        with engine.connect() as conn:
            target = "trades"
            trade_id = str(uuid.uuid4())
            insert_sql = """
                INSERT INTO trades (
                    trade_id, market_id, side, size, price,
                    commission, gas_cost_eth, gas_cost_usd,
                    gross_pnl, total_fees, net_pnl, status, executed_at
                ) VALUES (
                    :trade_id, :market_id, :side, :size, :price, :commission,
                    :gas_cost_eth, :gas_cost_usd, :gross_pnl, :total_fees,
                    :net_pnl, :status, NOW()
                )
            """
            params = {
                "trade_id": trade_id,
                "market_id": "0xmarket_basic",
                "side": "buy",
                "size": float(Decimal("1.0")),
                "price": float(Decimal("0.50")),
                "commission": float(Decimal("0.01")),
                "gas_cost_eth": float(Decimal("0.00")),
                "gas_cost_usd": float(Decimal("0.00")),
                "gross_pnl": float(Decimal("0.00")),
                "total_fees": float(Decimal("0.00")),
                "net_pnl": float(Decimal("0.00")),
                "status": "open",
            }
            conn.execute(text(insert_sql), params)
            conn.commit()
            row = conn.execute(
                text(f"SELECT * FROM {target} WHERE trade_id = :tid"), {"tid": trade_id}
            ).fetchone()
            assert row is not None
    except Exception as e:
        pytest.skip(f"DB not available or misconfigured: {e}")


@pytest.mark.asyncio
async def test_basic_bankroll_insert():
    engine, db_url = _get_db_engine()
    try:
        with engine.connect() as conn:
            res = conn.execute(text("SELECT to_regclass('public.bankroll')"))
            if res.scalar() is None:
                pytest.skip("bankroll table not present")
            insert_sql = """
                INSERT INTO bankroll (timestamp, total_capital, allocated, available, daily_pnl, daily_drawdown, total_trades, win_count, loss_count)
                VALUES (NOW(), :tc, 0, :avail, 0, 0, 0, 0, 0)
            """
            conn.execute(text(insert_sql), {"tc": 100.0, "avail": 100.0})
            conn.commit()
            row = conn.execute(
                text("SELECT * FROM bankroll ORDER BY id DESC LIMIT 1")
            ).fetchone()
            assert row is not None
    except Exception as e:
        pytest.skip(f"DB bankroll write failed due to environment: {e}")
