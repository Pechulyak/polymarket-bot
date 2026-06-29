"""
WhaleTradesRepo — единая точка записи в таблицу whale_trades.

Обеспечивает:
- Валидацию входных параметров
- Дедупликацию по tx_hash
- Автоматический lookup whale_id из таблицы whales
- Счётчики saved/rejected/duplicates
"""
from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)

# SQL для строк БЕЗ tx_hash (null/empty) — без ON CONFLICT
_INSERT_PLAIN = """
    INSERT INTO whale_trades
        (whale_id, wallet_address, market_id, market_title, side,
         size_usd, price, outcome, market_category, traded_at, tx_hash, source, token_id)
    VALUES
        (:whale_id, :wallet_address, :market_id, :market_title, :side,
         :size_usd, :price, :outcome, :market_category, :traded_at, :tx_hash, :source, :token_id)
"""

# SQL для строк С tx_hash — partial unique index (tx_hash IS NOT NULL AND tx_hash <> '')
_INSERT_ON_CONFLICT = """
    INSERT INTO whale_trades
        (whale_id, wallet_address, market_id, market_title, side,
         size_usd, price, outcome, market_category, traded_at, tx_hash, source, token_id)
    VALUES
        (:whale_id, :wallet_address, :market_id, :market_title, :side,
         :size_usd, :price, :outcome, :market_category, :traded_at, :tx_hash, :source, :token_id)
    ON CONFLICT (tx_hash) WHERE tx_hash IS NOT NULL AND tx_hash <> '' DO NOTHING
"""


class WhaleTradesRepo:
    """
    Репозиторий для записи whale_trades.
    
    Принимает session_factory (sqlalchemy.orm.sessionmaker) — синхронный.
    """
    
    def __init__(self, session_factory):
        """
        Args:
            session_factory: SQLAlchemy sessionmaker (синхронный).
        """
        self._session_factory = session_factory
        self._stats = {"saved": 0, "rejected": 0, "duplicates": 0}
        self._category_missing_count = 0
        self._burst_window_seconds: int = 900
        self._burst_threshold: int = 30
        self._burst_min_size_usd: Decimal = Decimal("50")
        self._burst_counters: dict[str, deque] = {}
        self._burst_blocked_count: int = 0
    
    def _check_burst(self, wallet_address: str, market_id: str, size_usd: Decimal, now: datetime) -> bool:
        if size_usd >= self._burst_min_size_usd:
            return False
        key = f"{wallet_address}:{market_id}"
        if key not in self._burst_counters:
            self._burst_counters[key] = deque()
        window = self._burst_counters[key]
        cutoff = now.timestamp() - self._burst_window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        window.append(now.timestamp())
        return len(window) > self._burst_threshold
    
    def save_trade(
        self,
        wallet_address: str,
        market_id: str,
        side: str,
        size_usd: Decimal,
        price: Decimal,
        outcome: Optional[str] = None,
        market_title: Optional[str] = None,
        market_category: Optional[str] = None,
        tx_hash: Optional[str] = None,
        source: str = "BACKFILL",
        traded_at: Optional[datetime] = None,
        token_id: Optional[str] = None,
    ) -> str:
        """
        Единственная точка записи в whale_trades.
        
        Returns:
            "saved" | "rejected" | "duplicate" | "burst_blocked"
        """
        # === ВАЛИДАЦИЯ ===
        
        # 1. side IN ('buy', 'sell')
        side_normalized = side.lower().strip() if side else None
        if side_normalized not in ("buy", "sell"):
            self._stats["rejected"] += 1
            logger.warning(
                "trade_rejected",
                reason="invalid_side",
                wallet=wallet_address,
                market_id=market_id,
                side=side,
            )
            return "rejected"
        
        # 2. size_usd > 0
        if size_usd <= 0:
            self._stats["rejected"] += 1
            logger.warning(
                "trade_rejected",
                reason="zero_or_negative_size",
                wallet=wallet_address,
                market_id=market_id,
                size_usd=str(size_usd),
            )
            return "rejected"
        
        # 3. price > 0
        if price <= 0:
            self._stats["rejected"] += 1
            logger.warning(
                "trade_rejected",
                reason="zero_or_negative_price",
                wallet=wallet_address,
                market_id=market_id,
                price=str(price),
            )
            return "rejected"
        
        # 4. Burst detection (только для свежих сделок < 2 часов)
        trade_time = traded_at if traded_at is not None else datetime.utcnow()
        is_recent = (datetime.utcnow() - trade_time).total_seconds() < 7200
        if is_recent and self._check_burst(wallet_address, market_id, size_usd, trade_time):
            self._burst_blocked_count += 1
            logger.warning(
                "trade_burst_blocked",
                wallet=wallet_address,
                market_id=market_id,
                size_usd=str(size_usd),
                burst_blocked_total=self._burst_blocked_count,
            )
            return "burst_blocked"
        
        # 5. market_category — если None/empty, установить 'unknown'
        if not market_category or not market_category.strip():
            market_category = "unknown"
            self._category_missing_count += 1
            # Первые 10 раз — warning каждый раз, потом — каждую сотню
            if self._category_missing_count <= 10 or self._category_missing_count % 100 == 0:
                logger.warning(
                    "market_category_missing",
                    wallet=wallet_address,
                    market_id=market_id,
                    occurrence=self._category_missing_count,
                )
        
        # 6. outcome — предупреждение, но НЕ отклонять
        if not outcome or not outcome.strip():
            logger.warning(
                "outcome_missing",
                wallet=wallet_address,
                market_id=market_id,
            )
        
        # === ПОДГОТОВКА ДАННЫХ ===
        
        # Normalize wallet_address
        wallet_address = wallet_address.lower().strip()
        
        # traded_at — если не передан, использовать now
        if traded_at is None:
            traded_at = datetime.utcnow()
        
        # Lookup whale_id из таблицы whales
        whale_id = self._lookup_whale_id(wallet_address)
        
        # === ЗАПИСЬ ===
        
        try:
            session = self._session_factory()
            try:
                # Дедупликация: проверка tx_hash перед INSERT
                if tx_hash and tx_hash.strip():
                    existing = session.execute(
                        text("SELECT 1 FROM whale_trades WHERE tx_hash = :tx_hash"),
                        {"tx_hash": tx_hash.strip()}
                    ).fetchone()
                    if existing:
                        self._stats["duplicates"] += 1
                        logger.debug(
                            "trade_duplicate",
                            tx_hash=tx_hash,
                            wallet=wallet_address,
                            market_id=market_id,
                        )
                        return "duplicate"
                
                # Выбор SQL в зависимости от наличия tx_hash
                tx_hash_val = tx_hash.strip() if tx_hash and tx_hash.strip() else None
                sql = _INSERT_ON_CONFLICT if tx_hash_val else _INSERT_PLAIN
                session.execute(
                    text(sql),
                    {
                        "whale_id": whale_id,
                        "wallet_address": wallet_address,
                        "market_id": market_id,
                        "market_title": market_title,
                        "side": side_normalized,
                        "size_usd": size_usd,
                        "price": price,
                        "outcome": outcome,
                        "market_category": market_category,
                        "traded_at": traded_at,
                        "tx_hash": tx_hash_val,
                        "source": source,
                        "token_id": token_id,
                    }
                )
                session.commit()
                self._stats["saved"] += 1
                logger.debug(
                    "trade_saved",
                    wallet=wallet_address,
                    market_id=market_id,
                    side=side_normalized,
                    size_usd=str(size_usd),
                    tx_hash=tx_hash,
                )
                return "saved"
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(
                    "trade_save_error",
                    error=str(e),
                    wallet=wallet_address,
                    market_id=market_id,
                )
                raise
            finally:
                session.close()
        except SQLAlchemyError:
            raise
        except Exception as e:
            logger.error(
                "trade_save_unexpected_error",
                error=str(e),
                wallet=wallet_address,
                market_id=market_id,
            )
            raise
    
    def _lookup_whale_id(self, wallet_address: str) -> Optional[int]:
        """Lookup whale_id из таблицы whales по wallet_address."""
        try:
            session = self._session_factory()
            try:
                result = session.execute(
                    text("SELECT id FROM whales WHERE wallet_address = :wallet"),
                    {"wallet": wallet_address.lower().strip()}
                ).fetchone()
                return result[0] if result else None
            finally:
                session.close()
        except SQLAlchemyError:
            # Таблица whales может не существовать или быть недоступна
            return None
        except Exception:
            return None
    
    def get_stats(self) -> dict:
        """Вернуть копию текущих счётчиков."""
        return {**self._stats, "burst_blocked": self._burst_blocked_count}
    
    def reset_stats(self) -> dict:
        """Сбросить счётчики, вернуть значения до сброса."""
        old = {**self._stats, "burst_blocked": self._burst_blocked_count}
        self._stats = {"saved": 0, "rejected": 0, "duplicates": 0}
        self._category_missing_count = 0
        self._burst_blocked_count = 0
        return old
