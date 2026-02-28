# -*- coding: utf-8 -*-
"""Whale Detector - Automatic whale identification from trade streams.

Monitors Polymarket trade feeds and automatically identifies whales
based on trading activity patterns.

Example:
    >>> from research.whale_detector import WhaleDetector, DetectedWhale
    >>>
    >>> async def on_whale_detected(whale):
    ...     print(f"New whale detected: {whale.wallet_address}")
    ...
    >>> detector = WhaleDetector(
    ...     min_trade_size=Decimal("50"),
    ...     min_trades_for_quality=10,
    ...     on_whale_detected=on_whale_detected,
    ...     database_url="postgresql://..."
    ... )
    >>> await detector.start()
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.research.polymarket_data_client import (
    PolymarketDataClient,
)
from src.research.whale_tracker import calculate_risk_score

logger = structlog.get_logger(__name__)


@dataclass
class TradeRecord:
    """Record of a single trade for whale detection.

    Attributes:
        trader: Trader wallet address
        market_id: Market identifier
        side: Trade side ("buy" or "sell")
        size_usd: Trade size in USD
        price: Execution price
        timestamp: Trade timestamp
        is_winner: Whether trade was winning (if known)
        pnl: Profit/loss (if known)
    """

    trader: str
    market_id: str
    side: str
    size_usd: Decimal
    price: Decimal
    timestamp: float
    is_winner: Optional[bool] = None
    pnl: Optional[Decimal] = None


@dataclass
class DetectedWhale:
    """Represents a whale identified by the detector.

    Attributes:
        wallet_address: Whale wallet address
        first_seen: When whale was first detected
        total_trades: Total number of trades observed
        total_volume: Total trading volume
        avg_trade_size: Average trade size
        win_count: Number of winning trades
        loss_count: Number of losing trades
        win_rate: Win rate as decimal
        daily_trades: Trades per day (rolling)
        risk_score: Calculated risk score (1-10)
        is_quality: Whether whale meets quality criteria
    """

    wallet_address: str
    first_seen: float
    total_trades: int = 0
    total_volume: Decimal = Decimal("0")
    avg_trade_size: Decimal = Decimal("0")
    win_count: int = 0
    loss_count: int = 0
    win_rate: Decimal = Decimal("0")
    daily_trades: int = 0
    risk_score: int = 5
    is_quality: bool = False
    # Stage 2: Discovery + Qualification + Ranking
    status: str = "discovered"  # discovered | qualified | ranked
    trades_last_3_days: int = 0
    days_active: int = 0


@dataclass
class DetectionConfig:
    """Configuration for whale detection.

    Attributes:
        min_trade_size: Minimum trade size to consider ($50 default)
        min_trades_for_quality: Min trades for quality status (10 default)
        daily_trade_threshold: Min trades per day to qualify as whale (5 default)
        quality_win_rate: Min win rate for quality (0.60 default)
    """

    min_trade_size: Decimal = Decimal("50")
    min_trades_for_quality: int = 10
    daily_trade_threshold: int = 5
    quality_win_rate: Decimal = Decimal("0.60")
    quality_volume: Decimal = Decimal("1000")


class WhaleDetector:
    """Automatic Whale Detector from trade streams.

    Monitors trade feeds and identifies whales based on:
    - Large trade size (>$50)
    - Repeated daily activity (5+ trades/day)
    - Profitability (tracked over time)

    Attributes:
        DETECTION_WINDOW_HOURS: Hours to track before quality assessment
    """

    DETECTION_WINDOW_HOURS = 24

    def __init__(
        self,
        config: Optional[DetectionConfig] = None,
        on_whale_detected: Optional[Callable[[DetectedWhale], Any]] = None,
        on_whale_updated: Optional[Callable[[DetectedWhale], Any]] = None,
        database_url: Optional[str] = None,
        polymarket_client: Optional[PolymarketDataClient] = None,
        polymarket_poll_interval_seconds: int = 60,
    ) -> None:
        """Initialize Whale Detector.

        Args:
            config: Detection configuration
            on_whale_detected: Callback when new whale is detected
            on_whale_updated: Callback when whale stats are updated
            database_url: PostgreSQL connection URL
            polymarket_client: Polymarket Data client for real-time trades
            polymarket_poll_interval_seconds: How often to poll (default 60 sec)
        """
        self.polymarket_client = polymarket_client
        self.polymarket_poll_interval = polymarket_poll_interval_seconds
        self.config = config or DetectionConfig()
        self.database_url = database_url

        self._trades: Dict[str, List[TradeRecord]] = defaultdict(list)
        self._detected_whales: Dict[str, DetectedWhale] = {}
        self._known_whales: Set[str] = set()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._polymarket_task: Optional[asyncio.Task] = None
        self._engine = None
        self._Session = None
        self._lock = asyncio.Lock()

        logger.info(
            "whale_detector_initialized",
            min_trade_size=str(self.config.min_trade_size),
            min_trades_for_quality=self.config.min_trades_for_quality,
            daily_trade_threshold=self.config.daily_trade_threshold,
        )

    def set_database(self, database_url: str) -> None:
        """Set database URL and initialize connection."""
        self.database_url = database_url
        self._engine = create_engine(database_url)
        self._Session = sessionmaker(bind=self._engine)
        logger.info("whale_detector_database_configured")

    async def _ensure_database(self) -> None:
        """Ensure database connection is available."""
        if not self.database_url:
            return
        if not self._engine:
            self._engine = create_engine(self.database_url)
            self._Session = sessionmaker(bind=self._engine)

    async def start(self) -> None:
        """Start the whale detector."""
        if self._running:
            logger.warning("whale_detector_already_running")
            return

        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())

        await self._load_known_whales()

        if self.polymarket_client:
            await self.start_polymarket_polling()

        logger.info("whale_detector_started")

    async def stop(self) -> None:
        """Stop the whale detector."""
        self._running = False

        await self.stop_polymarket_polling()

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info(
            "whale_detector_stopped",
            detected_whales=len(self._detected_whales),
        )

    async def _cleanup_loop(self) -> None:
        """Background cleanup of old trade data."""
        while self._running:
            try:
                await asyncio.sleep(3600)
                await self._cleanup_old_trades()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("cleanup_loop_error", error=str(e))

    async def _cleanup_old_trades(self) -> None:
        """Remove trades older than detection window."""
        cutoff = time.time() - (self.DETECTION_WINDOW_HOURS * 3600)
        async with self._lock:
            for trader in list(self._trades.keys()):
                self._trades[trader] = [
                    t for t in self._trades[trader] if t.timestamp > cutoff
                ]
                if not self._trades[trader]:
                    del self._trades[trader]

    async def _load_known_whales(self) -> None:
        """Load known whales from database."""
        await self._ensure_database()
        if not self._Session:
            return

        session = self._Session()
        try:
            query = text("""
                SELECT wallet_address FROM whales WHERE is_active = TRUE
            """)
            result = session.execute(query)
            for row in result:
                self._known_whales.add(row[0].lower())
                self._detected_whales[row[0].lower()] = DetectedWhale(
                    wallet_address=row[0].lower(),
                    first_seen=time.time(),
                )

            logger.info("known_whales_loaded", count=len(self._known_whales))

        except Exception as e:
            logger.error("load_known_whales_failed", error=str(e))
        finally:
            session.close()

    async def process_trade(
        self,
        trader: str,
        market_id: str,
        side: str,
        size_usd: Decimal,
        price: Decimal,
        timestamp: Optional[float] = None,
        is_winner: Optional[bool] = None,
        pnl: Optional[Decimal] = None,
    ) -> Optional[DetectedWhale]:
        """Process a trade and detect if trader is a whale.

        Args:
            trader: Trader wallet address
            market_id: Market identifier
            side: Trade side ("buy" or "sell")
            size_usd: Trade size in USD
            price: Execution price
            timestamp: Trade timestamp (default: now)
            is_winner: Whether trade was winning
            pnl: Profit/loss amount

        Returns:
            DetectedWhale if new whale detected, None otherwise
        """
        if size_usd < self.config.min_trade_size:
            return None

        trader = trader.lower()
        timestamp = timestamp or time.time()

        trade = TradeRecord(
            trader=trader,
            market_id=market_id,
            side=side,
            size_usd=size_usd,
            price=price,
            timestamp=timestamp,
            is_winner=is_winner,
            pnl=pnl,
        )

        async with self._lock:
            self._trades[trader].append(trade)

            whale = self._detected_whales.get(trader)
            is_new = False

            if not whale:
                whale = DetectedWhale(
                    wallet_address=trader,
                    first_seen=timestamp,
                )
                self._detected_whales[trader] = whale
                is_new = True

            self._update_whale_stats(whale)

            # Stage 2: Save ALL discovered whales (not just quality ones)
            # This ensures we track all candidates for qualification
            await self._save_whale_to_db(whale)
            
            if is_new:
                self._known_whales.add(trader)

                logger.info(
                    "new_whale_discovered",
                    address=trader[:10],
                    daily_trades=whale.daily_trades,
                    total_trades=whale.total_trades,
                    total_volume=str(whale.total_volume),
                    status=whale.status,
                )

                if self.on_whale_detected:
                    try:
                        await self.on_whale_detected(whale)
                    except Exception as e:
                        logger.error("whale_detected_callback_failed", error=str(e))

                return whale

            # Update when quality status changes
            if whale.daily_trades >= self.config.daily_trade_threshold:
                old_quality = whale.is_quality
                old_status = whale.status
                self._evaluate_quality(whale)

                # Log status change
                if whale.status != old_status:
                    logger.info(
                        "whale_status_changed",
                        address=trader[:10],
                        old_status=old_status,
                        new_status=whale.status,
                        risk_score=whale.risk_score,
                    )

                if whale.is_quality and not old_quality:
                    logger.info(
                        "whale_became_quality",
                        address=trader[:10],
                        win_rate=str(whale.win_rate),
                        risk_score=whale.risk_score,
                    )

                    if self.on_whale_updated:
                        try:
                            await self.on_whale_updated(whale)
                        except Exception as e:
                            logger.error("whale_updated_callback_failed", error=str(e))

        return None

    def _update_whale_stats(self, whale: DetectedWhale) -> None:
        """Update whale statistics from trade records.

        Args:
            whale: Whale to update
        """
        cutoff_24h = time.time() - 86400
        cutoff_72h = time.time() - (3 * 86400)  # 3 days for qualification
        cutoff_window = time.time() - (self.DETECTION_WINDOW_HOURS * 3600)

        recent_trades = [
            t for t in self._trades[whale.wallet_address] if t.timestamp > cutoff_24h
        ]
        trades_last_3_days = [
            t for t in self._trades[whale.wallet_address] if t.timestamp > cutoff_72h
        ]
        all_trades = [
            t for t in self._trades[whale.wallet_address] if t.timestamp > cutoff_window
        ]

        whale.total_trades = len(all_trades)
        whale.daily_trades = len(recent_trades)
        whale.trades_last_3_days = len(trades_last_3_days)
        
        # Calculate days_active (unique trading days)
        if all_trades:
            trading_days = set()
            for t in all_trades:
                # Convert timestamp to date string
                day = datetime.fromtimestamp(t.timestamp).strftime("%Y-%m-%d")
                trading_days.add(day)
            whale.days_active = len(trading_days)

        if all_trades:
            whale.total_volume = sum(t.size_usd for t in all_trades)
            whale.avg_trade_size = whale.total_volume / Decimal(len(all_trades))

        winners = [t for t in all_trades if t.is_winner is True]
        losers = [t for t in all_trades if t.is_winner is False]

        whale.win_count = len(winners)
        whale.loss_count = len(losers)

        total_known = whale.win_count + whale.loss_count
        if total_known > 0:
            whale.win_rate = Decimal(whale.win_count) / Decimal(total_known)

        self._evaluate_quality(whale)

    def _evaluate_quality(self, whale: DetectedWhale) -> None:
        """Evaluate if whale meets quality criteria.
        
        NOTE: This method now uses calculate_risk_score from whale_tracker
        as the SOURCE-OF-TRUTH for risk_score calculation.
        
        The risk_score is based on ACTIVITY metrics (not win_rate) because:
        - Polymarket Data API does NOT provide settlement outcomes
        - win_rate is always 0/unknown for prediction markets
        
        Args:
            whale: Whale to evaluate
        """
        # Use unified risk_score calculation from WhaleTracker
        # SOURCE-OF-TRUTH: ensures consistency across all modules
        whale.risk_score = calculate_risk_score(
            total_trades=whale.total_trades,
            avg_trade_size=whale.avg_trade_size,
            total_volume=whale.total_volume,
            trades_per_day=Decimal(whale.daily_trades),
            last_active=None,  # Not available in DetectedWhale
        )
        
        # Stage 2: Binary Qualification Gate
        # Activity-based criteria (NOT ROI-based - no settlement data available)
        #
        # Qualified if ALL of:
        # - total_trades >= 10 (lifetime)
        # - trades_last_3_days >= 3
        # - total_volume >= $500
        # - days_active >= 1 (at least one trading day)
        
        qualification_criteria = {
            "min_10_trades": whale.total_trades >= 10,
            "min_3_trades_3days": whale.trades_last_3_days >= 3,
            "min_500_volume": whale.total_volume >= Decimal("500"),
            "min_1_day_active": whale.days_active >= 1,
        }
        
        is_qualified = all(qualification_criteria.values())
        
        # Set status based on qualification
        if is_qualified:
            whale.status = "qualified"
            whale.is_quality = True
            logger.debug(
                "whale_qualified",
                address=whale.wallet_address[:10],
                total_trades=whale.total_trades,
                trades_last_3_days=whale.trades_last_3_days,
                total_volume=str(whale.total_volume),
                days_active=whale.days_active,
            )
        else:
            whale.status = "discovered"
            whale.is_quality = False
            # Log why not qualified (for debugging)
            failed_criteria = [k for k, v in qualification_criteria.items() if not v]
            if failed_criteria:
                logger.debug(
                    "whale_not_qualified",
                    address=whale.wallet_address[:10],
                    failed_criteria=failed_criteria,
                )

    async def _save_whale_to_db(self, whale: DetectedWhale) -> None:
        """Save whale to database.

        Args:
            whale: Whale to save
        """
        await self._ensure_database()
        if not self._Session:
            logger.warning("save_whale_db_no_session", address=whale.wallet_address[:10])
            return
        
        logger.info(
            "save_whale_to_db",
            address=whale.wallet_address[:10],
            total_trades=whale.total_trades,
            status=whale.status,
        )

        session = self._Session()
        try:
            query = text("""
                INSERT INTO whales (
                    wallet_address, total_trades, win_rate, total_profit_usd,
                    total_volume_usd, avg_trade_size_usd, last_active_at, risk_score,
                    status, trades_last_3_days, days_active, source, updated_at
                ) VALUES (
                    :wallet_address, :total_trades, :win_rate, :total_profit,
                    :total_volume, :avg_trade_size, NOW(), :risk_score,
                    :status, :trades_last_3_days, :days_active, 'auto_detected', NOW()
                )
                ON CONFLICT (wallet_address) DO UPDATE SET
                    total_trades = EXCLUDED.total_trades,
                    win_rate = EXCLUDED.win_rate,
                    total_profit_usd = EXCLUDED.total_profit_usd,
                    total_volume_usd = EXCLUDED.total_volume_usd,
                    avg_trade_size_usd = EXCLUDED.avg_trade_size_usd,
                    risk_score = EXCLUDED.risk_score,
                    status = EXCLUDED.status,
                    trades_last_3_days = EXCLUDED.trades_last_3_days,
                    days_active = EXCLUDED.days_active,
                    last_active_at = NOW(),
                    updated_at = NOW()
            """)
            session.execute(
                query,
                {
                    "wallet_address": whale.wallet_address,
                    "total_trades": whale.total_trades,
                    "win_rate": float(whale.win_rate),
                    "total_profit": float(
                        whale.total_volume * (whale.win_rate - Decimal("0.5")) * 2
                    ),
                    "total_volume": float(whale.total_volume),
                    "avg_trade_size": float(whale.avg_trade_size),
                    "risk_score": whale.risk_score,
                    "status": whale.status,
                    "trades_last_3_days": whale.trades_last_3_days,
                    "days_active": whale.days_active,
                },
            )
            session.commit()
            logger.debug("whale_saved_to_db", address=whale.wallet_address[:10])

        except Exception as e:
            logger.error("whale_save_failed", error=str(e))
            session.rollback()
        finally:
            session.close()

    async def save_trade_to_db(
        self,
        trader: str,
        market_id: str,
        side: str,
        size_usd: Decimal,
        price: Decimal,
        timestamp: Optional[float] = None,
    ) -> None:
        """Save trade to whale_trades table.

        Args:
            trader: Trader wallet address
            market_id: Market identifier
            side: Trade side
            size_usd: Trade size in USD
            price: Execution price
            timestamp: Trade timestamp
        """
        await self._ensure_database()
        if not self._Session:
            return

        session = self._Session()
        try:
            query = text("""
                SELECT id FROM whales WHERE wallet_address = :address
            """)
            result = session.execute(query, {"address": trader.lower()})
            row = result.fetchone()

            if not row:
                return

            whale_id = row[0]

            insert_query = text("""
                INSERT INTO whale_trades (
                    whale_id, market_id, side, size_usd, price, traded_at
                ) VALUES (
                    :whale_id, :market_id, :side, :size_usd, :price, :traded_at
                )
            """)
            session.execute(
                insert_query,
                {
                    "whale_id": whale_id,
                    "market_id": market_id,
                    "side": side,
                    "size_usd": float(size_usd),
                    "price": float(price),
                    "traded_at": datetime.fromtimestamp(timestamp or time.time()),
                },
            )
            session.commit()

        except Exception as e:
            logger.debug("trade_save_failed", error=str(e))
            session.rollback()
        finally:
            session.close()

    def get_detected_whales(self) -> List[DetectedWhale]:
        """Get all detected whales.

        Returns:
            List of DetectedWhale objects
        """
        return list(self._detected_whales.values())

    def get_quality_whales(self) -> List[DetectedWhale]:
        """Get whales that meet quality criteria.

        Returns:
            List of quality DetectedWhale objects
        """
        return [w for w in self._detected_whales.values() if w.is_quality]

    def get_whale(self, address: str) -> Optional[DetectedWhale]:
        """Get whale by address.

        Args:
            address: Whale wallet address

        Returns:
            DetectedWhale or None if not found
        """
        return self._detected_whales.get(address.lower())

    def is_known_whale(self, address: str) -> bool:
        """Check if address is a known whale.

        Args:
            address: Wallet address

        Returns:
            True if known whale
        """
        return address.lower() in self._known_whales

    def set_polymarket_client(self, client: PolymarketDataClient) -> None:
        """Set Polymarket Data client for real-time whale detection.

        Args:
            client: PolymarketDataClient instance
        """
        self.polymarket_client = client
        logger.info("polymarket_client_set")

    async def start_polymarket_polling(self) -> None:
        """Start polling Polymarket Data API for new whales."""
        if not self.polymarket_client:
            logger.warning("polymarket_polling_no_client")
            return

        if self._polymarket_task and not self._polymarket_task.done():
            logger.warning("polymarket_polling_already_running")
            return

        self._polymarket_task = asyncio.create_task(self._polymarket_poll_loop())
        logger.info(
            "polymarket_polling_started",
            interval_seconds=self.polymarket_poll_interval,
        )

    async def stop_polymarket_polling(self) -> None:
        """Stop Polymarket Data API polling."""
        if self._polymarket_task:
            self._polymarket_task.cancel()
            try:
                await self._polymarket_task
            except asyncio.CancelledError:
                pass

        logger.info("polymarket_polling_stopped")

    async def _polymarket_poll_loop(self) -> None:
        """Background loop to poll Polymarket Data API for whale data."""
        # Stage 2: Ranking update interval (every hour)
        ranking_interval = 3600  # 1 hour
        last_ranking_update = time.time()
        
        while self._running:
            try:
                await self._fetch_polymarket_whales()
                
                # Stage 2: Periodic ranking update every hour
                current_time = time.time()
                if current_time - last_ranking_update >= ranking_interval:
                    top_whales = self.get_top_whales(limit=10)
                    if top_whales:
                        logger.info(
                            "ranking_updated",
                            top_count=len(top_whales),
                            top_addresses=[w.wallet_address[:10] for w in top_whales[:3]],
                        )
                    last_ranking_update = current_time
                
                await asyncio.sleep(self.polymarket_poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("polymarket_poll_error", error=str(e))
                await asyncio.sleep(60)

    async def _fetch_polymarket_whales(self) -> None:
        """Fetch whales from Polymarket Data API and update database."""
        if not self.polymarket_client:
            return

        try:
            min_size = self.config.quality_volume
            aggregated = await self.polymarket_client.aggregate_by_address(
                limit=500,
                min_size_usd=min_size,
            )

            new_whales = 0
            for address, stats in aggregated.items():
                logger.info(
                    "whale_check",
                    address=address[:10],
                    total_trades=stats.total_trades,
                    min_required=self.config.min_trades_for_quality,
                    is_known=address.lower() in self._known_whales,
                )
                if stats.total_trades < self.config.min_trades_for_quality:
                    logger.info("whale_skipped_min_trades", address=address[:10], total_trades=stats.total_trades)
                    continue

                if address.lower() in self._known_whales:
                    logger.info("whale_skipped_known", address=address[:10])
                    continue

                whale = DetectedWhale(
                    wallet_address=address.lower(),
                    first_seen=stats.last_seen if stats.last_seen else time.time(),
                    total_trades=stats.total_trades,
                    total_volume=stats.total_volume_usd,
                    avg_trade_size=stats.avg_trade_size_usd,
                )

                if stats.total_trades >= self.config.min_trades_for_quality:
                    self._detected_whales[address.lower()] = whale
                    await self._save_whale_to_db(whale)
                    self._known_whales.add(address.lower())
                    new_whales += 1

                    logger.info(
                        "polymarket_new_whale",
                        address=address[:10],
                        total_trades=stats.total_trades,
                        volume_usd=str(stats.total_volume_usd),
                    )

                    if self.on_whale_detected:
                        try:
                            await self.on_whale_detected(whale)
                        except Exception as e:
                            logger.error(
                                "polymarket_whale_callback_failed", error=str(e)
                            )

            if new_whales > 0:
                logger.info(
                    "polymarket_fetch_complete",
                    new_whales=new_whales,
                    total_traders=len(aggregated),
                )

        except Exception as e:
            logger.error("polymarket_fetch_failed", error=str(e))

    async def fetch_and_process_polymarket(self) -> List[DetectedWhale]:
        """Manually fetch and process whales from Polymarket Data API.

        Returns:
            List of newly detected whales
        """
        if not self.polymarket_client:
            logger.warning("polymarket_fetch_no_client")
            return []

        await self._fetch_polymarket_whales()
        return [
            w
            for w in self._detected_whales.values()
            if w.daily_trades >= self.config.daily_trade_threshold
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics.

        Returns:
            Dict with statistics
        """
        quality = self.get_quality_whales()
        return {
            "total_tracked": len(self._detected_whales),
            "quality_whales": len(quality),
            "known_whales": len(self._known_whales),
        }

    def get_top_whales(self, limit: int = 10) -> List[DetectedWhale]:
        """Get top ranked whales by activity score.
        
        Ranking is based on a composite score:
        - Lower risk_score = better
        - Higher trades_last_3_days = better
        - Higher total_volume = better
        
        Only returns whales with status='qualified' or 'ranked'.

        Args:
            limit: Maximum number of whales to return (default: 10)

        Returns:
            List of top whales sorted by rank score (best first)
        """
        # Get all qualified whales
        qualified = [
            w for w in self._detected_whales.values()
            if w.status in ("qualified", "ranked")
        ]
        
        if not qualified:
            return []
        
        # Calculate rank score (higher = better)
        def rank_score(whale: DetectedWhale) -> float:
            # Invert risk_score (lower is better, so 10-risk gives higher for better)
            risk_component = (10 - whale.risk_score) * 10
            # Activity component: trades in last 3 days
            activity_component = whale.trades_last_3_days * 5
            # Volume component (log scale for large volumes)
            volume_component = float(whale.total_volume) / 1000 if whale.total_volume > 0 else 0
            return risk_component + activity_component + volume_component
        
        # Sort by rank score descending
        ranked = sorted(qualified, key=rank_score, reverse=True)
        
        # Update status to 'ranked' for top N
        for i, whale in enumerate(ranked[:limit]):
            if whale.status != "ranked":
                whale.status = "ranked"
        
        return ranked[:limit]
