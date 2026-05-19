# -*- coding: utf-8 -*-
"""Sample data builders for TRD-443 close roundtrip tests.

Helpers produce minimally-valid INSERT'ы in test DB. Each builder returns
inserted row id for chaining.

NOTE: This file contains ONLY utility functions — no tests.
Tests live in TASK 2-D-2 files.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import text


def insert_whale(
    engine,
    wallet_address: str = "0xtest_whale",
    whale_id: Optional[int] = None,
) -> int:
    """Insert a whale, return id. If whale_id specified, force that id."""
    with engine.connect() as conn:
        if whale_id is not None:
            result = conn.execute(text("""
                INSERT INTO whales (id, wallet_address, source_new)
                VALUES (:id, :wallet, 'TRIGGER_TEST')
                RETURNING id
            """), {"id": whale_id, "wallet": wallet_address})
        else:
            result = conn.execute(text("""
                INSERT INTO whales (wallet_address, source_new)
                VALUES (:wallet, 'TRIGGER_TEST')
                RETURNING id
            """), {"wallet": wallet_address})
        rid = result.scalar()
        conn.commit()
    return rid


def insert_open_roundtrip(
    engine,
    whale_id: int,
    wallet_address: str,
    market_id: str = "0xmarket_test",
    outcome: str = "Yes",
    open_price: Decimal = Decimal("0.50"),
    open_size_usd: Decimal = Decimal("100.00"),
    opened_at: Optional[datetime] = None,
    position_key: Optional[str] = None,
) -> int:
    """Insert a single OPEN roundtrip, return id.

    Defaults make a sensible OPEN: opened_at = NOW() - 1h.
    Position_key auto-generated as 'wallet:market:outcome' if not provided.
    """
    if opened_at is None:
        opened_at = datetime.now(timezone.utc) - timedelta(hours=1)
    if position_key is None:
        position_key = f"{wallet_address}:{market_id}:{outcome or 'unknown'}"

    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO whale_trade_roundtrips (
                whale_id, wallet_address, position_key,
                market_id, outcome,
                open_trade_id, open_side, open_price, open_size_usd, opened_at,
                status, created_at, updated_at
            ) VALUES (
                :whale_id, :wallet, :pkey,
                :market, :outcome,
                NULL, 'buy', :oprice, :osize, :opened_at,
                'OPEN', NOW(), NOW()
            )
            RETURNING id
        """), {
            "whale_id": whale_id,
            "wallet": wallet_address,
            "pkey": position_key,
            "market": market_id,
            "outcome": outcome,
            "oprice": open_price,
            "osize": open_size_usd,
            "opened_at": opened_at,
        })
        rid = result.scalar()
        conn.commit()
    return rid


def insert_whale_trade(
    engine,
    wallet_address: str,
    market_id: str = "0xmarket_test",
    outcome: str = "Yes",
    side: str = "sell",
    price: Decimal = Decimal("0.60"),
    size_usd: Decimal = Decimal("80.00"),
    traded_at: Optional[datetime] = None,
) -> int:
    """Insert a single whale_trade, return id.

    Defaults: traded_at = NOW(), price=0.60, size_usd=80.
    """
    if traded_at is None:
        traded_at = datetime.now(timezone.utc)

    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO whale_trades (
                wallet_address, market_id, outcome, side, price,
                size_usd, traded_at, tx_hash, source
            ) VALUES (
                :wallet, :market, :outcome, :side, :price,
                :size_usd, :traded_at, :tx, 'TRIGGER_TEST'
            )
            RETURNING id
        """), {
            "wallet": wallet_address,
            "market": market_id,
            "outcome": outcome,
            "side": side,
            "price": price,
            "size_usd": size_usd,
            "traded_at": traded_at,
            "tx": f"0xtx_{wallet_address}_{traded_at.timestamp()}",
        })
        rid = result.scalar()
        conn.commit()
    return rid


def get_roundtrip(engine, roundtrip_id: str) -> dict:
    """Fetch a single roundtrip row as dict for assertions."""
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM whale_trade_roundtrips WHERE id = :id"),
            {"id": roundtrip_id},
        )
        row = result.fetchone()
        if row is None:
            return {}
        return dict(row._mapping)