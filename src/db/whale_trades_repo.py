"""
WhaleTradesRepo — единая точка записи в таблицу whale_trades.

Обеспечивает:
- Валидацию входных параметров
- Дедупликацию по tx_hash
- Автоматический lookup whale_id из таблицы whales
- Счётчики saved/rejected/duplicates
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)


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
    ) -> str:
        """
        Единственная точка записи в whale_trades.
        
        Returns:
            "saved" | "rejected" | "duplicate"
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
        
        # 4. market_category — если None/empty, установить 'unknown'
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
        
        # 5. outcome — предупреждение, но НЕ отклонять
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
                
                # INSERT
                session.execute(
                    text("""
                        INSERT INTO whale_trades (
                            whale_id, wallet_address, market_id, market_title,
                            side, size_usd, price, outcome, market_category,
                            traded_at, tx_hash, source
                        ) VALUES (
                            :whale_id, :wallet_address, :market_id, :market_title,
                            :side, :size_usd, :price, :outcome, :market_category,
                            :traded_at, :tx_hash, :source
                        )
                    """),
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
                        "tx_hash": tx_hash.strip() if tx_hash else None,
                        "source": source,
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
        return dict(self._stats)
    
    def reset_stats(self) -> dict:
        """Сбросить счётчики, вернуть значения до сброса."""
        old = dict(self._stats)
        self._stats = {"saved": 0, "rejected": 0, "duplicates": 0}
        self._category_missing_count = 0
        return old
