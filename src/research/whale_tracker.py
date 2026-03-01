# -*- coding: utf-8 -*-
"""Whale Tracker - Fetch and analyze whale trading data from Polymarket.

Uses Polymarket Data API to fetch whale positions and trades,
calculate statistics, and provide quality signals for copy trading.

Example:
    >>> from research.whale_tracker import WhaleTracker, WhaleStats
    >>> from decimal import Decimal
    >>>
    >>> tracker = WhaleTracker(database_url="postgresql://...")
    >>> positions = await tracker.fetch_whale_positions("0xWALLET")
    >>> trades = await tracker.fetch_whale_trades("0xWALLET", limit=100)
    >>> stats = await tracker.calculate_stats("0xWALLET")
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import List, Optional

import aiohttp
import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = structlog.get_logger(__name__)


def _mask_database_url(url: str) -> str:
    """Mask password in database URL for safe logging."""
    if not url:
        return "None"
    import re
    return re.sub(r':([^@]+)@', ':****@', url)


class StatsMode(Enum):
    """Statistics calculation mode.
    
    Defines what data is available and how to calculate metrics:
    
    - REALIZED: Actual settled trades with known outcomes.
      Requires: is_winner field from API (currently NOT available).
      Status: NOT IMPLEMENTED - Polymarket Data API does not provide settlement data.
    
    - UNREALIZED_PROXY: Use unrealizedPnl from positions snapshot.
      Pros: Real-time P&L from API.
      Cons: Only shows current snapshot, not actual trading profit.
    
    - ACTIVITY_ONLY: Only activity metrics (trades count, avg size, turnover).
      No P&L or win rate. Safest approach when outcomes unknown.
      Always available regardless of API capabilities.
    """
    
    # Not yet implemented - requires settlement data from API
    REALIZED = "realized"
    
    # Use unrealizedPnl from positions (current snapshot)
    UNREALIZED_PROXY = "unrealized_proxy"
    
    # Activity metrics only (trades count, avg size, turnover)
    ACTIVITY_ONLY = "activity_only"


@dataclass
class WhalePosition:
    """Represents a whale's position in a market.

    Attributes:
        market_id: Market/token identifier
        outcome: Position outcome (Yes/No)
        size: Position size in USD
        entry_price: Entry price
        current_price: Current market price
        unrealized_pnl: Unrealized profit/loss
        opened_at: Position open timestamp
    """

    market_id: str
    outcome: str
    size: Decimal
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    opened_at: datetime


@dataclass
class WhaleTrade:
    """Represents a single whale trade.

    Attributes:
        trade_id: Unique trade identifier
        market_id: Market identifier
        side: Trade side ("buy" or "sell")
        size_usd: Trade size in USD
        price: Execution price
        timestamp: Trade timestamp
        fee: Trade fee
    """

    trade_id: str
    market_id: str
    side: str
    size_usd: Decimal
    price: Decimal
    timestamp: datetime
    fee: Decimal = Decimal("0")


@dataclass
class WhaleStats:
    """Statistical summary of a whale's trading activity.
    
    IMPORTANT: win_rate and total_profit_usd are NOT reliable because:
    - Polymarket Data API does NOT provide `is_winner` field
    - Trade outcomes are unknown until market settlement
    - BUY != win, SELL != loss (incorrect assumption removed)
    
    Use stats_mode to understand what metrics are available:
    - ACTIVITY_ONLY: Only activity metrics (safe default)
    - UNREALIZED_PROXY: Uses unrealizedPnl from positions snapshot

    Attributes:
        wallet_address: Whale wallet address
        stats_mode: How statistics were calculated (see StatsMode enum)
        total_trades: Total number of trades
        win_rate: DEPRECATED - always 0, kept for compatibility
        total_profit_usd: DEPRECATED - use unrealized_pnl_usd instead
        unrealized_pnl_usd: Unrealized P&L from positions snapshot (if available)
        avg_trade_size_usd: Average trade size in USD
        total_volume_usd: Total trading volume in USD
        trades_per_day: Average trades per day
        last_active_at: Last activity timestamp
        risk_score: Risk score 1-10 (1 = best)
    """

    wallet_address: str
    stats_mode: StatsMode = StatsMode.ACTIVITY_ONLY
    total_trades: int = 0
    # Deprecated fields - kept for backward compatibility
    win_rate: Decimal = Decimal("0")
    total_profit_usd: Decimal = Decimal("0")
    # New fields with clear semantics
    unrealized_pnl_usd: Decimal = Decimal("0")
    avg_trade_size_usd: Decimal = Decimal("0")
    total_volume_usd: Decimal = Decimal("0")
    trades_per_day: Decimal = Decimal("0")
    last_active_at: Optional[datetime] = None
    risk_score: int = 5


class WhaleTracker:
    """Whale Tracker for Polymarket Data API.

    Fetches whale positions and trades, calculates statistics,
    and manages whale database for copy trading.

    Attributes:
        data_api_url: Polymarket Data API base URL
        database_url: PostgreSQL connection URL
    """

    DATA_API_URL = "https://data-api.polymarket.com"

    # Criteria for quality whale detection
    # NOTE: win_rate removed - API does not provide settlement outcomes
    QUALITY_WHALE_CRITERIA = {
        "min_trades": 50,  # Reduced from 100 (more inclusive)
        "min_avg_size": Decimal("50.0"),
        "min_total_volume": Decimal("1000.0"),  # Add volume threshold
        "max_inactive_days": 30,
    }

    def __init__(
        self,
        database_url: Optional[str] = None,
        data_api_url: Optional[str] = None,
    ) -> None:
        """Initialize Whale Tracker.

        Args:
            database_url: PostgreSQL connection URL
            data_api_url: Polymarket Data API URL (optional)
        """
        self.database_url = database_url
        self.data_api_url = data_api_url or self.DATA_API_URL
        self._engine = None
        self._Session = None
        self._session = None
        self._http_session: Optional[aiohttp.ClientSession] = None

    def set_database(self, database_url: str) -> None:
        """Set database URL and initialize connection.

        Args:
            database_url: PostgreSQL connection URL
        """
        self.database_url = database_url
        self._engine = create_engine(database_url)
        self._Session = sessionmaker(bind=self._engine)
        logger.info("whale_tracker_database_configured", url=_mask_database_url(database_url))

    async def _ensure_database(self) -> None:
        """Ensure database connection is available."""
        if not self.database_url:
            logger.warning("whale_tracker_no_database")
            return

        if not self._engine:
            self._engine = create_engine(self.database_url)
            self._Session = sessionmaker(bind=self._engine)

    async def _ensure_http_session(self) -> aiohttp.ClientSession:
        """Ensure HTTP session is available."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def fetch_whale_positions(self, wallet_address: str) -> List[WhalePosition]:
        """Fetch current positions for a whale address.

        Uses Polymarket Data API:
            GET /positions?user=0xADDRESS

        Args:
            wallet_address: Whale wallet address (0x...)

        Returns:
            List of WhalePosition objects
        """
        url = f"{self.data_api_url}/positions"
        params = {"user": wallet_address.lower()}

        try:
            session = await self._ensure_http_session()
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "whale_positions_api_error",
                        status=resp.status,
                        address=wallet_address[:10],
                    )
                    return []

                data = await resp.json()
                positions = []

                for item in data:
                    # Handle timestamp - could be ISO string or Unix timestamp (int)
                    timestamp_val = item.get("timestamp")
                    if timestamp_val is None:
                        opened_at = datetime.now()
                    elif isinstance(timestamp_val, (int, float)):
                        # Unix timestamp
                        opened_at = datetime.fromtimestamp(timestamp_val)
                    elif isinstance(timestamp_val, datetime):
                        # Already a datetime object
                        opened_at = timestamp_val
                    else:
                        # ISO string - ensure it's a string
                        try:
                            opened_at = datetime.fromisoformat(str(timestamp_val))
                        except (ValueError, TypeError):
                            opened_at = datetime.now()

                    position = WhalePosition(
                        market_id=item.get("conditionId", item.get("tokenId", "")),
                        outcome=item.get("outcome", "Yes"),
                        size=Decimal(str(item.get("size", 0))),
                        entry_price=Decimal(str(item.get("avgPrice", 0))),
                        current_price=Decimal(str(item.get("currentPrice", 0))),
                        unrealized_pnl=Decimal(str(item.get("unrealizedPnl", 0))),
                        opened_at=opened_at,
                    )
                    positions.append(position)

                logger.info(
                    "whale_positions_fetched",
                    address=wallet_address[:10],
                    count=len(positions),
                )
                return positions

        except asyncio.TimeoutError:
            logger.warning("whale_positions_timeout", address=wallet_address[:10])
        except Exception as e:
            logger.error(
                "whale_positions_fetch_error",
                address=wallet_address[:10],
                error=str(e),
            )

        return []

    async def fetch_whale_trades(
        self, wallet_address: str, limit: int = 100
    ) -> List[WhaleTrade]:
        """Fetch recent trades for a whale address.

        Uses Polymarket Data API:
            GET /trades?user=0xADDRESS&limit=100

        Args:
            wallet_address: Whale wallet address (0x...)
            limit: Maximum number of trades to fetch (default: 100)

        Returns:
            List of WhaleTrade objects
        """
        url = f"{self.data_api_url}/trades"
        params = {"user": wallet_address.lower(), "limit": limit}

        try:
            session = await self._ensure_http_session()
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "whale_trades_api_error",
                        status=resp.status,
                        address=wallet_address[:10],
                    )
                    return []

                data = await resp.json()
                trades = []

                for item in data:
                    # Handle timestamp - could be ISO string or Unix timestamp (int)
                    timestamp_val = item.get("timestamp")
                    if timestamp_val is None:
                        trade_timestamp = datetime.now()
                    elif isinstance(timestamp_val, (int, float)):
                        # Unix timestamp
                        trade_timestamp = datetime.fromtimestamp(timestamp_val)
                    elif isinstance(timestamp_val, datetime):
                        # Already a datetime object
                        trade_timestamp = timestamp_val
                    else:
                        # ISO string - ensure it's a string
                        try:
                            trade_timestamp = datetime.fromisoformat(str(timestamp_val))
                        except (ValueError, TypeError):
                            trade_timestamp = datetime.now()

                    trade = WhaleTrade(
                        trade_id=item.get("id", ""),
                        market_id=item.get("conditionId", item.get("tokenId", "")),
                        side=item.get("side", "buy").lower(),
                        size_usd=Decimal(str(item.get("amount", 0))),
                        price=Decimal(str(item.get("price", 0))),
                        timestamp=trade_timestamp,
                        fee=Decimal(str(item.get("fee", 0))),
                    )
                    trades.append(trade)

                logger.info(
                    "whale_trades_fetched",
                    address=wallet_address[:10],
                    count=len(trades),
                )
                return trades

        except asyncio.TimeoutError:
            logger.warning("whale_trades_timeout", address=wallet_address[:10])
        except Exception as e:
            logger.error(
                "whale_trades_fetch_error",
                address=wallet_address[:10],
                error=str(e),
            )

        return []

    async def calculate_stats(
        self,
        wallet_address: str,
        stats_mode: StatsMode = StatsMode.ACTIVITY_ONLY,
    ) -> WhaleStats:
        """Calculate statistical summary for a whale.
        
        IMPORTANT: This method no longer calculates win_rate or realized profit
        because Polymarket Data API does NOT provide settlement outcomes.
        
        Available modes:
        - ACTIVITY_ONLY (default): Activity metrics only (safe)
        - UNREALIZED_PROXY: Add unrealizedPnl from positions snapshot
        
        Activity metrics (always available):
        - total_trades: Number of trades
        - avg_trade_size_usd: Average trade size
        - total_volume_usd: Total trading volume
        - trades_per_day: Trading frequency
        
        Args:
            wallet_address: Whale wallet address
            stats_mode: Statistics calculation mode (default: ACTIVITY_ONLY)

        Returns:
            WhaleStats object with calculated statistics
        """
        trades = await self.fetch_whale_trades(wallet_address, limit=500)

        if not trades:
            return WhaleStats(wallet_address=wallet_address)

        # === ACTIVITY METRICS (always available) ===
        total_size = Decimal("0")
        for trade in trades:
            total_size += trade.size_usd

        total_trades = len(trades)
        avg_size = (
            total_size / Decimal(total_trades) if total_trades > 0 else Decimal("0")
        )
        
        # Calculate trades per day
        time_span = trades[0].timestamp - trades[-1].timestamp
        days_active = max(time_span.total_seconds() / 86400, 1)  # At least 1 day
        trades_per_day = Decimal(total_trades) / Decimal(days_active)

        # === UNREALIZED P&L (if requested and available) ===
        unrealized_pnl = Decimal("0")
        if stats_mode == StatsMode.UNREALIZED_PROXY:
            positions = await self.fetch_whale_positions(wallet_address)
            for position in positions:
                unrealized_pnl += position.unrealized_pnl

        # === RISK SCORE (based on activity metrics, not win_rate) ===
        risk_score = self._calculate_risk_score(
            total_trades=total_trades,
            avg_trade_size=avg_size,
            total_volume=total_size,
            trades_per_day=trades_per_day,
            last_active=trades[0].timestamp if trades else None,
        )

        return WhaleStats(
            wallet_address=wallet_address,
            stats_mode=stats_mode,
            total_trades=total_trades,
            # Deprecated fields - kept for compatibility but always 0
            win_rate=Decimal("0"),
            total_profit_usd=Decimal("0"),
            # New fields
            unrealized_pnl_usd=unrealized_pnl,
            avg_trade_size_usd=avg_size,
            total_volume_usd=total_size,
            trades_per_day=trades_per_day,
            last_active_at=trades[0].timestamp if trades else None,
            risk_score=risk_score,
        )

    def _calculate_risk_score(
        self,
        total_trades: int,
        avg_trade_size: Decimal,
        total_volume: Decimal,
        trades_per_day: Decimal,
        last_active: Optional[datetime],
    ) -> int:
        """Calculate risk score (1-10) for a whale.
        
        NOTE: This scoring is based on ACTIVITY metrics only, since win_rate
        is not available from Polymarket Data API (no settlement data).
        
        SOURCE-OF-TRUTH: This is the canonical risk_score implementation.
        All other modules (WhaleDetector, copy_trading_engine, etc.) should
        use this function to ensure consistent scoring.
        
        Scoring logic:
        - 1-3: Elite (high volume, consistent activity)
        - 4-6: Good (moderate volume/activity)
        - 7-8: Low activity or small trades
        - 9-10: High risk (inactive, low volume)

        Args:
            total_trades: Total number of trades
            avg_trade_size: Average trade size in USD
            total_volume: Total trading volume in USD
            trades_per_day: Average trades per day
            last_active: Last active timestamp

        Returns:
            Risk score 1-10 (1 = best)
        """
        return calculate_risk_score(
            total_trades=total_trades,
            avg_trade_size=avg_trade_size,
            total_volume=total_volume,
            trades_per_day=trades_per_day,
            last_active=last_active,
        )

    def is_quality_whale(self, stats: WhaleStats) -> bool:
        """Check if whale meets quality criteria.
        
        NOTE: win_rate is no longer used for quality assessment because
        Polymarket Data API does not provide settlement outcomes.
        
        Criteria (based on ACTIVITY metrics):
        - min_trades >= 50 (reduced from 100)
        - min_total_volume >= $1000
        - min_avg_size >= $50
        - inactive <= 30 days

        Args:
            stats: WhaleStats to evaluate

        Returns:
            True if quality whale, False otherwise
        """
        criteria = self.QUALITY_WHALE_CRITERIA

        if stats.total_trades < criteria["min_trades"]:
            return False

        # Use total_volume instead of win_rate
        if stats.total_volume_usd < criteria.get("min_total_volume", Decimal("1000")):
            return False

        if stats.avg_trade_size_usd < criteria["min_avg_size"]:
            return False

        if stats.last_active_at:
            days_inactive = (datetime.now() - stats.last_active_at).days
            if days_inactive > criteria["max_inactive_days"]:
                return False

        return True

    async def save_whale(self, stats: WhaleStats) -> bool:
        """Save whale statistics to database.

        Args:
            stats: WhaleStats to save

        Returns:
            True if saved successfully, False otherwise
        """
        await self._ensure_database()

        if not self._Session:
            return False

        session = self._Session()
        try:
            query = text("""
                INSERT INTO whales (
                    wallet_address, total_trades, win_rate, total_profit_usd,
                    avg_trade_size_usd, last_active_at, risk_score, updated_at
                ) VALUES (
                    :wallet_address, :total_trades, :win_rate, :total_profit_usd,
                    :avg_trade_size_usd, :last_active_at, :risk_score, NOW()
                )
                ON CONFLICT (wallet_address) DO UPDATE SET
                    total_trades = EXCLUDED.total_trades,
                    win_rate = EXCLUDED.win_rate,
                    total_profit_usd = EXCLUDED.total_profit_usd,
                    avg_trade_size_usd = EXCLUDED.avg_trade_size_usd,
                    last_active_at = EXCLUDED.last_active_at,
                    risk_score = EXCLUDED.risk_score,
                    updated_at = NOW()
            """)
            session.execute(
                query,
                {
                    "wallet_address": stats.wallet_address.lower(),
                    "total_trades": stats.total_trades,
                    "win_rate": float(stats.win_rate),
                    "total_profit_usd": float(stats.total_profit_usd),
                    "avg_trade_size_usd": float(stats.avg_trade_size_usd),
                    "last_active_at": stats.last_active_at,
                    "risk_score": stats.risk_score,
                },
            )
            session.commit()
            logger.info("whale_saved", address=stats.wallet_address[:10])
            return True

        except Exception as e:
            logger.error(
                "whale_save_failed", address=stats.wallet_address[:10], error=str(e)
            )
            session.rollback()
            return False
        finally:
            session.close()

    async def load_quality_whales(
        self,
        min_win_rate: Decimal = Decimal("0.60"),
        min_trades: int = 100,
        max_risk_score: int = 6,
    ) -> List[WhaleStats]:
        """Load quality whales from database.

        Args:
            min_win_rate: Minimum win rate (default: 60%)
            min_trades: Minimum total trades (default: 100)
            max_risk_score: Maximum risk score (default: 6)

        Returns:
            List of WhaleStats for qualified whales
        """
        await self._ensure_database()

        if not self._Session:
            return []

        session = self._Session()
        try:
            query = text("""
                SELECT
                    wallet_address, total_trades, win_rate, total_profit_usd,
                    avg_trade_size_usd, last_active_at, risk_score
                FROM whales
                WHERE is_active = TRUE
                    AND win_rate >= :min_win_rate
                    AND total_trades >= :min_trades
                    AND risk_score <= :max_risk_score
                ORDER BY win_rate DESC, total_trades DESC
                LIMIT 50
            """)
            result = session.execute(
                query,
                {
                    "min_win_rate": float(min_win_rate),
                    "min_trades": min_trades,
                    "max_risk_score": max_risk_score,
                },
            )

            whales = []
            for row in result:
                whales.append(
                    WhaleStats(
                        wallet_address=row[0],
                        total_trades=row[1],
                        win_rate=Decimal(str(row[2])),
                        total_profit_usd=Decimal(str(row[3])),
                        avg_trade_size_usd=Decimal(str(row[4])),
                        last_active_at=row[5],
                        risk_score=row[6],
                    )
                )

            logger.info("quality_whales_loaded", count=len(whales))
            return whales

        except Exception as e:
            logger.error("load_whales_failed", error=str(e))
            return []
        finally:
            session.close()

    async def save_whale_trade(
        self,
        whale_id: int,
        market_id: str,
        side: str,
        size_usd: Decimal,
        price: Decimal,
        is_winner: Optional[bool] = None,
        profit_usd: Optional[Decimal] = None,
    ) -> bool:
        """Save a whale trade to database.

        Args:
            whale_id: Whale database ID
            market_id: Market identifier
            side: Trade side ("buy" or "sell")
            size_usd: Trade size in USD
            price: Execution price
            is_winner: Whether trade was winning
            profit_usd: Profit in USD

        Returns:
            True if saved successfully
        """
        await self._ensure_database()

        if not self._Session:
            return False

        session = self._Session()
        try:
            query = text("""
                INSERT INTO whale_trades (
                    whale_id, market_id, side, size_usd, price,
                    is_winner, profit_usd, traded_at
                ) VALUES (
                    :whale_id, :market_id, :side, :size_usd, :price,
                    :is_winner, :profit_usd, NOW()
                )
            """)
            session.execute(
                query,
                {
                    "whale_id": whale_id,
                    "market_id": market_id,
                    "side": side,
                    "size_usd": float(size_usd),
                    "price": float(price),
                    "is_winner": is_winner,
                    "profit_usd": float(profit_usd) if profit_usd else None,
                },
            )
            session.commit()
            return True

        except Exception as e:
            logger.error("whale_trade_save_failed", error=str(e))
            session.rollback()
            return False
        finally:
            session.close()

    async def get_whale_id(self, wallet_address: str) -> Optional[int]:
        """Get whale database ID by wallet address.

        Args:
            wallet_address: Whale wallet address

        Returns:
            Whale ID if found, None otherwise
        """
        await self._ensure_database()

        if not self._Session:
            return None

        session = self._Session()
        try:
            query = text("SELECT id FROM whales WHERE wallet_address = :address")
            result = session.execute(query, {"address": wallet_address.lower()})
            row = result.fetchone()
            return row[0] if row else None
        finally:
            session.close()

    async def close(self) -> None:
        """Clean up resources."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()


# Standalone function for external use (e.g., testing)
def calculate_risk_score(
    total_trades: int,
    avg_trade_size: Decimal,
    total_volume: Decimal,
    trades_per_day: Decimal,
    last_active: Optional[datetime] = None,
) -> int:
    """Calculate risk score (1-10) for a whale.
    
    NOTE: This scoring is based on ACTIVITY metrics only, since win_rate
    is not available from Polymarket Data API (no settlement data).
    
    SOURCE-OF-TRUTH: This is the canonical risk_score implementation.
    All other modules (WhaleDetector, copy_trading_engine, etc.) should
    use this function to ensure consistent scoring.
    
    Scoring logic:
    - 1-3: Elite (high volume, consistent activity)
    - 4-6: Good (moderate volume/activity)
    - 7-8: Low activity or small trades
    - 9-10: High risk (inactive, low volume)

    Args:
        total_trades: Total number of trades
        avg_trade_size: Average trade size in USD
        total_volume: Total trading volume in USD
        trades_per_day: Average trades per day
        last_active: Last active timestamp

    Returns:
        Risk score 1-10 (1 = best)
    """
    score = 5

    # Elite: High volume and consistent activity
    if total_volume >= Decimal("500000") and total_trades >= 500:
        if total_trades >= 1000 and trades_per_day >= Decimal("5"):
            score = 1
        else:
            score = 2
    # Good: Moderate volume
    elif total_volume >= Decimal("100000") and total_trades >= 200:
        if total_trades >= 500:
            score = 3
        else:
            score = 4
    # Moderate: Some activity
    elif total_volume >= Decimal("50000") and total_trades >= 50:
        score = 5
    elif total_volume >= Decimal("10000") and total_trades >= 20:
        score = 6
    # Low activity
    elif total_trades >= 10:
        score = 7
    else:
        score = 8

    # Inactivity penalty
    if last_active:
        days_inactive = (datetime.now() - last_active).days
        if days_inactive > 30:
            score = min(score + 2, 10)
        elif days_inactive > 14:
            score = min(score + 1, 10)

    return score
