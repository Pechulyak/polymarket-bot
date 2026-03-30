# -*- coding: utf-8 -*-
"""Unified whale trade writer - единая точка записи в whale_trades.

Все модули используют только этот метод для записи сделок китов.

Categories (из CLOB API tags[0]):
    - Sports: ["Sports", "Soccer", "FIFA World Cup", ...]
    - Weather: ["Weather", "Recurring", "Seoul", "Daily Temperature", ...]
    - Crypto: ["Crypto", "Bitcoin", "Up/Down", ...]
    - Politics: ["Politics", "Elections", "2024", ...]
    - Economics: ["Economics", "Fed", "Interest Rates", ...]

Source: docs/API_MARKET_TYPES_AUDIT.md (TRD-417)
"""

import logging
from decimal import Decimal
from typing import Optional
from datetime import datetime

import structlog

logger = structlog.get_logger(__name__)

# Primary category mapping from CLOB API tags[0]
# Source: API_MARKET_TYPES_AUDIT.md section 2.2
PRIMARY_CATEGORY_MAPPING = {
    # Direct category matches
    "Sports": "Sports",
    "Weather": "Weather",
    "Crypto": "Crypto",
    "Politics": "Politics",
    "Economics": "Economics",
    
    # Known variations from Polymarket
    "Elections": "Politics",
    "Business": "Economics",
    "Science": "Other",
    "Entertainment": "Other",
    "Technology": "Other",
    "Health": "Other",
    "World": "Politics",
    "US Politics": "Politics",
    "World Politics": "Politics",
}

# Keywords for fuzzy matching (lowercase)
CATEGORY_KEYWORDS = {
    "sports": "Sports",
    "weather": "Weather",
    "crypto": "Crypto",
    "bitcoin": "Crypto",
    "ethereum": "Crypto",
    "up/down": "Crypto",
    "politics": "Politics",
    "election": "Politics",
    "economics": "Economics",
    "fed": "Economics",
    "interest": "Economics",
    "gdp": "Economics",
}


def normalize_category(tags: list[str]) -> Optional[str]:
    """Нормализует теги в категорию (использует tags[0] как primary).
    
    Args:
        tags: Список тегов из CLOB API, напр. ["Sports", "Soccer", "FIFA World Cup"]
    
    Returns:
        Нормализованная категория: Sports, Weather, Crypto, Politics, Economics или None
    """
    if not tags:
        return None
    
    # Primary category is always tags[0]
    primary_tag = tags[0]
    if primary_tag in PRIMARY_CATEGORY_MAPPING:
        return PRIMARY_CATEGORY_MAPPING[primary_tag]
    
    # Check direct match for other tags
    for tag in tags[1:]:
        if tag in PRIMARY_CATEGORY_MAPPING:
            return PRIMARY_CATEGORY_MAPPING[tag]
    
    # Fuzzy keyword matching
    all_tags_text = " ".join(tags).lower()
    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in all_tags_text:
            return category
    
    # Default for unknown
    logger.debug("unknown_category_tags", tags=tags[:3])
    return "Other"


async def save_whale_trade(
    session,
    wallet_address: str,
    market_id: str,
    side: str,
    size_usd: Decimal,
    price: Decimal,
    outcome: Optional[str] = None,
    market_title: Optional[str] = None,
    market_category: Optional[str] = None,
    market_tags: Optional[list[str]] = None,
    tx_hash: Optional[str] = None,
    source: str = "REALTIME",
    whale_id: Optional[int] = None,
    traded_at: Optional[datetime] = None,
) -> bool:
    """
    Единственный метод записи в whale_trades.
    
    Все модули используют только его.
    Дедупликация по tx_hash если передан.
    whale_id определяется из wallet_address если не передан явно.
    
    Args:
        session: DB session
        wallet_address: Адрес кошелька кита
        market_id: ID рынка
        side: buy/sell
        size_usd: Размер в USD
        price: Цена
        outcome: Исход (Yes/No/Up/Down/TeamName)
        market_title: Название рынка
        market_category: Категория рынка (опционально, auto-derived из tags если не передано)
        market_tags: Теги из CLOB API (для авто-определения категории)
        tx_hash: Hash транзакции (для дедупликации)
        source: Источник (REALTIME, POLLER, BACKFILL, etc)
        whale_id: ID кита в таблице whales (опционально)
    
    Returns:
        True если успешно, False если ошибка или дубликат
    """
    try:
        # Auto-derive category from tags if not provided
        if not market_category and market_tags:
            market_category = normalize_category(market_tags)
        
        # Connect tags list for storage
        tags_str = ",".join(market_tags) if market_tags else None
        
        # Дедупликация по tx_hash
        if tx_hash:
            # Use raw SQL for simpler deduplication check
            from sqlalchemy import text
            result = await session.execute(
                text("SELECT 1 FROM whale_trades WHERE tx_hash = :tx_hash"),
                {"tx_hash": tx_hash}
            )
            if result.fetchone():
                logger.debug("skipping_duplicate_trade", tx_hash=tx_hash[:16])
                return False
        
        # Определяем whale_id если не передан
        if whale_id is None and wallet_address:
            from sqlalchemy import text
            result = await session.execute(
                text("SELECT id FROM whales WHERE wallet_address = :addr"),
                {"addr": wallet_address.lower()}
            )
            row = result.fetchone()
            if row:
                whale_id = row[0]
        
        # Determine outcome - normalize for binary markets
        normalized_outcome = outcome
        if outcome:
            # Normalize Yes/No and Up/Down to standard case
            if outcome.lower() in ["yes", "no"]:
                normalized_outcome = outcome.capitalize()
            elif outcome.lower() in ["up", "down"]:
                normalized_outcome = outcome.capitalize()
        
        # Normalize side
        normalized_side = side.lower()
        if normalized_side not in ["buy", "sell"]:
            normalized_side = side.lower()
        
        # Use raw SQL insert for reliability
        from sqlalchemy import text
        result = await session.execute(
            text("""
                INSERT INTO whale_trades (
                    whale_id, wallet_address, market_id, market_title,
                    side, size_usd, price, outcome, traded_at,
                    tx_hash, source, market_category
                ) VALUES (
                    :whale_id, :wallet_address, :market_id, :market_title,
                    :side, :size_usd, :price, :outcome, :traded_at,
                    :tx_hash, :source, :market_category
                )
            """),
            {
                "whale_id": whale_id,
                "wallet_address": wallet_address.lower() if wallet_address else None,
                "market_id": market_id,
                "market_title": market_title,
                "side": normalized_side,
                "size_usd": float(size_usd),
                "price": float(price),
                "outcome": normalized_outcome,
                "traded_at": traded_at if traded_at else datetime.utcnow(),
                "tx_hash": tx_hash,
                "source": source,
                "market_category": market_category,
            }
        )
        
        await session.commit()
        
        # Check rowcount - True if inserted, False if no row was inserted
        inserted = result.rowcount > 0
        
        if inserted:
            logger.info(
                "whale_trade_saved",
                wallet=wallet_address[:10] if wallet_address else None,
                side=normalized_side,
                size_usd=float(size_usd),
                price=float(price),
                market_id=market_id[:20],
                category=market_category,
            )
        return inserted
        
    except Exception as e:
        logger.error(
            "whale_trade_save_failed",
            error=str(e),
            wallet=wallet_address[:10] if wallet_address else None,
            market_id=market_id[:20] if market_id else None,
        )
        await session.rollback()
        return False


# Convenience function for quick saves
async def save_whale_trade_simple(
    session,
    wallet_address: str,
    market_id: str,
    side: str,
    size_usd: Decimal,
    price: Decimal,
    tx_hash: Optional[str] = None,
    source: str = "REALTIME",
) -> bool:
    """Упрощённая версия save_whale_trade без дополнительных полей."""
    return await save_whale_trade(
        session=session,
        wallet_address=wallet_address,
        market_id=market_id,
        side=side,
        size_usd=size_usd,
        price=price,
        tx_hash=tx_hash,
        source=source,
    )
