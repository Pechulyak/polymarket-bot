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
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

import aiohttp
import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = structlog.get_logger(__name__)


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

    Attributes:
        wallet_address: Whale wallet address
        total_trades: Total number of trades
        win_rate: Win rate as decimal (0.0 to 1.0)
        total_profit_usd: Total profit in USD
        avg_trade_size_usd: Average trade size in USD
        last_active_at: Last activity timestamp
        risk_score: Risk score 1-10 (1 = best)
    """

    wallet_address: str
    total_trades: int = 0
    win_rate: Decimal = Decimal("0")
    total_profit_usd: Decimal = Decimal("0")
    avg_trade_size_usd: Decimal = Decimal("0")
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

    QUALITY_WHALE_CRITERIA = {
        "min_trades": 100,
        "min_win_rate": Decimal("0.60"),
        "min_avg_size": Decimal("50.0"),
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
        logger.info("whale_tracker_database_configured", url=database_url[:50])

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
                    position = WhalePosition(
                        market_id=item.get("conditionId", item.get("tokenId", "")),
                        outcome=item.get("outcome", "Yes"),
                        size=Decimal(str(item.get("size", 0))),
                        entry_price=Decimal(str(item.get("avgPrice", 0))),
                        current_price=Decimal(str(item.get("currentPrice", 0))),
                        unrealized_pnl=Decimal(str(item.get("unrealizedPnl", 0))),
                        opened_at=datetime.fromisoformat(
                            item.get("timestamp", datetime.now().isoformat())
                        ),
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
                    trade = WhaleTrade(
                        trade_id=item.get("id", ""),
                        market_id=item.get("conditionId", item.get("tokenId", "")),
                        side=item.get("side", "buy").lower(),
                        size_usd=Decimal(str(item.get("amount", 0))),
                        price=Decimal(str(item.get("price", 0))),
                        timestamp=datetime.fromisoformat(
                            item.get("timestamp", datetime.now().isoformat())
                        ),
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

    async def calculate_stats(self, wallet_address: str) -> WhaleStats:
        """Calculate statistical summary for a whale.

        Analyzes recent trades to calculate:
        - Win rate
        - Total profit
        - Average trade size
        - Risk score (1-10)

        Args:
            wallet_address: Whale wallet address

        Returns:
            WhaleStats object with calculated statistics
        """
        trades = await self.fetch_whale_trades(wallet_address, limit=500)

        if not trades:
            return WhaleStats(wallet_address=wallet_address)

        wins = 0
        total_profit = Decimal("0")
        total_size = Decimal("0")

        for trade in trades:
            total_size += trade.size_usd

            if trade.side.lower() == "buy":
                if trade.size_usd > 0:
                    wins += 1
                    total_profit += trade.size_usd * (Decimal("1") - trade.price)
            else:
                if trade.size_usd > 0:
                    total_profit += trade.size_usd * trade.price

        total_trades = len(trades)
        win_rate = (
            Decimal(wins) / Decimal(total_trades) if total_trades > 0 else Decimal("0")
        )
        avg_size = (
            total_size / Decimal(total_trades) if total_trades > 0 else Decimal("0")
        )

        risk_score = self._calculate_risk_score(
            win_rate=win_rate,
            total_trades=total_trades,
            avg_trade_size=avg_size,
            last_active=trades[0].timestamp if trades else None,
        )

        return WhaleStats(
            wallet_address=wallet_address,
            total_trades=total_trades,
            win_rate=win_rate,
            total_profit_usd=total_profit,
            avg_trade_size_usd=avg_size,
            last_active_at=trades[0].timestamp if trades else None,
            risk_score=risk_score,
        )

    def _calculate_risk_score(
        self,
        win_rate: Decimal,
        total_trades: int,
        avg_trade_size: Decimal,
        last_active: Optional[datetime],
    ) -> int:
        """Calculate risk score (1-10) for a whale.

        Scoring:
        - 1-3: Elite (>70% WR, $500k+ volume)
        - 4-6: Good (60-70% WR, $100k+ volume)
        - 7-8: Moderate (50-60% WR, $50k+ volume)
        - 9-10: High risk (<50% WR or <30 days active)

        Args:
            win_rate: Win rate as decimal
            total_trades: Total number of trades
            avg_trade_size: Average trade size
            last_active: Last active timestamp

        Returns:
            Risk score 1-10 (1 = best)
        """
        score = 5

        if win_rate >= Decimal("0.70"):
            if total_trades >= 1000 and avg_trade_size >= Decimal("500"):
                score = 1
            elif total_trades >= 500:
                score = 2
            else:
                score = 3
        elif win_rate >= Decimal("0.60"):
            if total_trades >= 500 and avg_trade_size >= Decimal("100"):
                score = 4
            elif total_trades >= 200:
                score = 5
            else:
                score = 6
        elif win_rate >= Decimal("0.50"):
            score = 7
        else:
            score = 9

        if last_active:
            days_inactive = (datetime.now() - last_active).days
            if days_inactive > 30:
                score = min(score + 1, 10)

        return score

    def is_quality_whale(self, stats: WhaleStats) -> bool:
        """Check if whale meets quality criteria.

        Criteria:
        - min_trades >= 100
        - win_rate >= 60%
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

        if stats.win_rate < criteria["min_win_rate"]:
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
