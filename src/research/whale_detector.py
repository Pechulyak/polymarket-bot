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

from src.data.storage.market_title_cache import get_market_title
from src.research.polymarket_data_client import (
    PolymarketDataClient,
)
from src.research.whale_tracker import calculate_risk_score

logger = structlog.get_logger(__name__)


def convert_outcome_to_yes_no(outcome: Optional[str], outcome_index: Optional[int] = None) -> Optional[str]:
    """Convert Polymarket API outcome to Yes/No format.
    
    Polymarket API can return:
    - outcome: "Up"/"Down" or "Yes"/"No" 
    - outcomeIndex: 0 (Yes/Up) or 1 (No/Down)
    
    This function normalizes to "Yes"/"No" for database storage.
    
    Args:
        outcome: Raw outcome string from API (Up/Down or Yes/No)
        outcome_index: Optional outcomeIndex (0 = Yes, 1 = No)
    
    Returns:
        Normalized outcome: "Yes" or "No", or None if unknown
    """
    if outcome_index is not None:
        return "Yes" if outcome_index == 0 else "No"
    
    if outcome:
        outcome_lower = outcome.lower()
        if outcome_lower in ("yes", "no"):
            return outcome  # Already normalized
        elif outcome_lower in ("up", "down"):
            # Convert Up->Yes, Down->No
            return "Yes" if outcome_lower == "up" else "No"
    
    return None


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
    trades_last_7_days: int = 0  # For dual-path qualification
    days_active: int = 0
    name: str = ""  # Trader's name from Polymarket profile
    qualification_path: Optional[str] = None  # ACTIVE | CONVICTION | None


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

    DETECTION_WINDOW_HOURS = 72  # Must be >= 3 days for trades_last_3_days calculation

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
        self.on_whale_detected = on_whale_detected
        self.on_whale_updated = on_whale_updated

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
            
            # Also save trade to whale_trades (ingestion pipeline fix)
            # This is the canonical source for whale_trades
            market_title = await get_market_title(market_id)
            await self.save_trade_to_db(
                trader=trader,
                market_id=market_id,
                side=side,
                size_usd=size_usd,
                price=price,
                timestamp=timestamp,
                market_title=market_title,
                source="BACKFILL",
            )
            
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
        cutoff_7d = time.time() - (7 * 86400)  # 7 days for dual-path qualification
        cutoff_window = time.time() - (self.DETECTION_WINDOW_HOURS * 3600)

        recent_trades = [
            t for t in self._trades[whale.wallet_address] if t.timestamp > cutoff_24h
        ]
        trades_last_3_days = [
            t for t in self._trades[whale.wallet_address] if t.timestamp > cutoff_72h
        ]
        trades_last_7_days = [
            t for t in self._trades[whale.wallet_address] if t.timestamp > cutoff_7d
        ]
        all_trades = [
            t for t in self._trades[whale.wallet_address] if t.timestamp > cutoff_window
        ]

        whale.total_trades = len(all_trades)
        whale.daily_trades = len(recent_trades)
        whale.trades_last_3_days = len(trades_last_3_days)
        whale.trades_last_7_days = len(trades_last_7_days)
        
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

        # Calculate dual-path qualification
        whale.qualification_path = self._calculate_qualification_path(
            total_trades=whale.total_trades,
            total_volume_usd=whale.total_volume,
            avg_trade_size_usd=whale.avg_trade_size,
            trades_last_7_days=whale.trades_last_7_days,
            days_active=whale.days_active,
            risk_score=whale.risk_score,
        )

    def _calculate_qualification_path(
        self,
        total_trades: int,
        total_volume_usd: Decimal,
        avg_trade_size_usd: Decimal,
        trades_last_7_days: int,
        days_active: int,
        risk_score: int,
    ) -> Optional[str]:
        """Calculate dual-path qualification for whale.
        
        ACTIVE path: 
            - total_trades >= 10
            - total_volume_usd >= 500
            - trades_last_7_days >= 3
            - days_active >= 1
            - risk_score <= 6
        
        CONVICTION path:
            - total_volume_usd >= 10000
            - avg_trade_size_usd >= 2000
            - trades_last_7_days >= 1
            - days_active >= 1
            - risk_score <= 6
        
        Priority: ACTIVE if both paths qualify
        
        Returns:
            'ACTIVE', 'CONVICTION', or None if not qualified
        """
        active_path = (
            total_trades >= 10 and
            total_volume_usd >= Decimal("500") and
            trades_last_7_days >= 3 and
            days_active >= 1 and
            risk_score <= 6
        )
        
        conviction_path = (
            total_volume_usd >= Decimal("10000") and
            avg_trade_size_usd >= Decimal("2000") and
            trades_last_7_days >= 1 and
            days_active >= 1 and
            risk_score <= 6
        )
        
        if active_path:
            logger.debug(
                "whale_qualified_active_path",
                total_trades=total_trades,
                total_volume_usd=str(total_volume_usd),
                trades_last_7_days=trades_last_7_days,
            )
            return "ACTIVE"
        elif conviction_path:
            logger.debug(
                "whale_qualified_conviction_path",
                total_volume_usd=str(total_volume_usd),
                avg_trade_size_usd=str(avg_trade_size_usd),
                trades_last_7_days=trades_last_7_days,
            )
            return "CONVICTION"
        else:
            logger.debug(
                "whale_not_qualified_dual_path",
                total_trades=total_trades,
                total_volume_usd=str(total_volume_usd),
                trades_last_7_days=trades_last_7_days,
                risk_score=risk_score,
            )
            return None

    async def refresh_qualification(self) -> int:
        """Refresh qualification for all whales based on recent trades.
        
        This method re-calculates qualification_path for whales that have
        new trades in the last 24 hours. It ensures the qualified list
        stays up-to-date with currently active traders.
        
        Returns:
            Number of whales that were re-qualified
        """
        await self._ensure_database()
        if not self._Session:
            return 0
        
        refreshed = 0
        session = self._Session()
        try:
            # Get whales with recent trades (last 24h)
            query = text("""
                SELECT 
                    w.id,
                    w.wallet_address,
                    w.total_trades,
                    w.total_volume_usd,
                    w.avg_trade_size_usd,
                    w.risk_score,
                    COALESCE(w.days_active, 0) as days_active,
                    COUNT(wt.id) as trades_last_24h,
                    COUNT(DISTINCT DATE(wt.traded_at)) as days_active_24h
                FROM whales w
                INNER JOIN whale_trades wt ON LOWER(w.wallet_address) = LOWER(wt.wallet_address)
                WHERE wt.traded_at >= NOW() - INTERVAL '24 hours'
                GROUP BY w.id, w.wallet_address, w.total_trades, w.total_volume_usd, 
                         w.avg_trade_size_usd, w.risk_score, w.days_active
            """)
            result = session.execute(query)
            
            for row in result:
                whale_id, wallet_address, total_trades, total_volume, avg_size, risk_score, days_active, trades_24h, days_24h = row
                
                # Calculate trades_last_7_days estimate (use 24h trades as minimum)
                trades_last_7_days = max(trades_24h, 1)
                
                # Re-calculate qualification path
                qualification_path = self._calculate_qualification_path(
                    total_trades=total_trades,
                    total_volume_usd=total_volume or Decimal("0"),
                    avg_trade_size_usd=avg_size or Decimal("0"),
                    trades_last_7_days=trades_last_7_days,
                    days_active=max(days_active, days_24h or 1),
                    risk_score=risk_score or 5,
                )
                
                if qualification_path:
                    # Update whale with new qualification
                    update_query = text("""
                        UPDATE whales 
                        SET qualification_path = :qualification_path,
                            trades_last_7_days = :trades_last_7_days,
                            days_active = :days_active,
                            last_active_at = NOW(),
                            updated_at = NOW()
                        WHERE id = :whale_id
                    """)
                    session.execute(update_query, {
                        "qualification_path": qualification_path,
                        "trades_last_7_days": trades_last_7_days,
                        "days_active": max(days_active, days_24h or 1),
                        "whale_id": whale_id,
                    })
                    refreshed += 1
            
            session.commit()
            logger.info("qualification_refresh_complete", refreshed=refreshed)
            
        except Exception as e:
            logger.error("qualification_refresh_failed", error=str(e))
            session.rollback()
        finally:
            session.close()
        
        return refreshed

    async def update_whale_activity_counters(self) -> int:
        """Update activity counters for all whales based on whale_trades table.
        
        This method recalculates:
        - trades_last_3_days: COUNT of trades in last 3 days
        - trades_last_7_days: COUNT of trades in last 7 days  
        - days_active: COUNT of DISTINCT trading days
        
        Returns:
            Number of whales updated
        """
        await self._ensure_database()
        if not self._Session:
            return 0
        
        updated = 0
        session = self._Session()
        try:
            # Update trades_last_3_days
            update_3d = text("""
                UPDATE whales w
                SET trades_last_3_days = t.trade_count,
                    last_active_at = NOW(),
                    updated_at = NOW()
                FROM (
                    SELECT wallet_address, COUNT(*) as trade_count
                    FROM whale_trades
                    WHERE traded_at >= NOW() - INTERVAL '3 days'
                    GROUP BY wallet_address
                ) t
                WHERE LOWER(w.wallet_address) = LOWER(t.wallet_address)
                AND w.trades_last_3_days != t.trade_count
            """)
            session.execute(update_3d)
            
            # Update trades_last_7_days
            update_7d = text("""
                UPDATE whales w
                SET trades_last_7_days = t.trade_count,
                    last_active_at = NOW(),
                    updated_at = NOW()
                FROM (
                    SELECT wallet_address, COUNT(*) as trade_count
                    FROM whale_trades
                    WHERE traded_at >= NOW() - INTERVAL '7 days'
                    GROUP BY wallet_address
                ) t
                WHERE LOWER(w.wallet_address) = LOWER(t.wallet_address)
                AND w.trades_last_7_days != t.trade_count
            """)
            session.execute(update_7d)
            
            # Update days_active
            update_days = text("""
                UPDATE whales w
                SET days_active = t.days,
                    last_active_at = NOW(),
                    updated_at = NOW()
                FROM (
                    SELECT wallet_address, COUNT(DISTINCT DATE(traded_at)) as days
                    FROM whale_trades
                    GROUP BY wallet_address
                ) t
                WHERE LOWER(w.wallet_address) = LOWER(t.wallet_address)
                AND w.days_active != t.days
            """)
            session.execute(update_days)
            
            session.commit()
            
            # Get count of updated whales
            count_query = text("""
                SELECT COUNT(*) FROM whales 
                WHERE updated_at >= NOW() - INTERVAL '1 second'
            """)
            result = session.execute(count_query)
            updated = result.scalar() or 0
            
            logger.info("activity_counters_updated", whales_updated=updated)
            
        except Exception as e:
            logger.error("activity_counters_update_failed", error=str(e))
            session.rollback()
        finally:
            session.close()
        
        return updated

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
                    status, trades_last_3_days, trades_last_7_days, days_active, 
                    qualification_path, source, updated_at, notes
                ) VALUES (
                    :wallet_address, :total_trades, :win_rate, :total_profit,
                    :total_volume, :avg_trade_size, NOW(), :risk_score,
                    :status, :trades_last_3_days, :trades_last_7_days, :days_active,
                    :qualification_path, 'auto_detected', NOW(), :notes
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
                    trades_last_7_days = EXCLUDED.trades_last_7_days,
                    days_active = EXCLUDED.days_active,
                    qualification_path = EXCLUDED.qualification_path,
                    last_active_at = NOW(),
                    updated_at = NOW(),
                    notes = EXCLUDED.notes
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
                    "trades_last_7_days": whale.trades_last_7_days,
                    "days_active": whale.days_active,
                    "qualification_path": whale.qualification_path,
                    "notes": whale.name if whale.name else None,
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
        tx_hash: Optional[str] = None,
        market_title: Optional[str] = None,
        source: str = "BACKFILL",
        outcome: Optional[str] = None,
    ) -> bool:
        """Save trade to whale_trades table.

        Uses wallet_address as primary identifier (whale_id is optional).
        Implements idempotent upsert using tx_hash to prevent duplicates.

        Args:
            trader: Trader wallet address
            market_id: Market identifier
            side: Trade side
            size_usd: Trade size in USD
            price: Execution price
            timestamp: Trade timestamp
            tx_hash: Transaction hash for deduplication
            market_title: Market question/title from Polymarket API
            source: Data source (REALTIME, BACKFILL, TRIGGER_TEST)
            outcome: Trade outcome (Yes/No). If API returns Up/Down, convert using: outcomeIndex 0 = Yes, 1 = No

        Returns:
            True if trade was saved, False if it was a duplicate.
        """
        await self._ensure_database()
        if not self._Session:
            return

        trader_lower = trader.lower()
        timestamp = timestamp or time.time()
        traded_at = datetime.fromtimestamp(timestamp)

        session = self._Session()
        try:
            # Check for duplicate using tx_hash if provided
            if tx_hash:
                dup_check = text("""
                    SELECT id FROM whale_trades WHERE tx_hash = :tx_hash
                """)
                result = session.execute(dup_check, {"tx_hash": tx_hash})
                if result.fetchone():
                    logger.debug("trade_duplicate_skip", tx_hash=tx_hash[:16] if tx_hash else None)
                    return False

            # Try to get whale_id if whale exists
            whale_id = None
            try:
                query = text("""
                    SELECT id FROM whales WHERE LOWER(wallet_address) = LOWER(:address)
                """)
                result = session.execute(query, {"address": trader_lower})
                row = result.fetchone()
                if row:
                    whale_id = row[0]
            except Exception:
                pass  # whale_id is optional

            # Insert trade with tx_hash for deduplication
            insert_query = text("""
                INSERT INTO whale_trades (
                    whale_id, wallet_address, market_id, market_title, side, size_usd, price, outcome, traded_at, tx_hash, source
                ) VALUES (
                    :whale_id, :wallet_address, :market_id, :market_title, :side, :size_usd, :price, :outcome, :traded_at, :tx_hash, :source
                )
            """)
            session.execute(
                insert_query,
                {
                    "whale_id": whale_id,
                    "wallet_address": trader_lower,
                    "market_id": market_id,
                    "market_title": market_title,
                    "side": side,
                    "size_usd": float(size_usd),
                    "price": float(price),
                    "outcome": outcome,
                    "traded_at": traded_at,
                    "tx_hash": tx_hash,
                    "source": source,
                },
            )
            session.commit()
            logger.info(
                "whale_trade_saved",
                wallet_address=trader_lower[:10],
                market_id=market_id[:20] if market_id else "unknown",
                side=side,
                size_usd=str(size_usd),
            )
            
            logger.debug(
                "whale_trade_saved",
                wallet_address=trader_lower[:10],
                market_id=market_id[:20],
                side=side,
                size_usd=str(size_usd),
            )
            
            return True

        except Exception as e:
            logger.info("trade_save_failed", error=str(e), trader=trader_lower[:10] if trader_lower else "unknown")
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
        
        # Qualification refresh interval (every hour)
        qualification_interval = 3600  # 1 hour
        last_qualification_refresh = time.time()
        
        while self._running:
            try:
                await self._fetch_polymarket_whales()
                
                current_time = time.time()
                
                # Stage 2: Periodic ranking update every hour
                if current_time - last_ranking_update >= ranking_interval:
                    top_whales = self.get_top_whales(limit=10)
                    if top_whales:
                        logger.info(
                            "ranking_updated",
                            top_count=len(top_whales),
                            top_addresses=[w.wallet_address[:10] for w in top_whales[:3]],
                        )
                    last_ranking_update = current_time
                
                # Qualification refresh every hour (for whales with recent trades)
                if current_time - last_qualification_refresh >= qualification_interval:
                    refreshed = await self.refresh_qualification()
                    if refreshed > 0:
                        logger.info(
                            "qualification_refreshed",
                            refreshed=refreshed,
                        )
                    # Also refresh activity counters from whale_trades table
                    activity_updated = await self.update_whale_activity_counters()
                    if activity_updated > 0:
                        logger.info(
                            "activity_counters_refreshed",
                            whales_updated=activity_updated,
                        )
                    last_qualification_refresh = current_time
                
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

        saved_trades_count = 0
        skipped_duplicates_count = 0

        try:
            min_size = self.config.quality_volume
            
            # Also fetch individual trades for whale_trades ingestion
            # First get the raw trades before aggregation
            trades = await self.polymarket_client.fetch_recent_trades(
                limit=500,
                min_size_usd=min_size,
            )
            
            # Save each trade to whale_trades table
            for trade in trades:
                try:
                    # Determine side from trade
                    side = "buy" if trade.side.upper() == "BUY" else "sell"
                    
                    # Get market_id from condition_id
                    market_id = trade.condition_id or ""
                    
                    # Convert outcome to Yes/No format using helper function
                    normalized_outcome = convert_outcome_to_yes_no(trade.outcome)
                    
                    # Save trade to database with tx_hash for deduplication
                    await self.save_trade_to_db(
                        trader=trade.trader,
                        market_id=market_id,
                        side=side,
                        size_usd=trade.size_usd,
                        price=trade.price,
                        timestamp=float(trade.timestamp),
                        tx_hash=trade.tx_hash,
                        market_title=trade.market_title,
                        source="BACKFILL",
                        outcome=normalized_outcome,
                    )
                    saved_trades_count += 1
                except Exception as e:
                    logger.debug("trade_save_error", error=str(e), trader=trade.trader[:10] if trade.trader else "unknown")
            
            # Now get aggregated stats
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

                # Check if whale is already known
                is_known = address.lower() in self._known_whales
                
                # Calculate trades_last_3_days, trades_last_7_days and days_active
                # NOTE: Polymarket API only returns recent trades, not full history
                # We use total_trades as a proxy for activity since high trade count
                # implies recent activity
                current_time = time.time()
                three_days_ago = current_time - (3 * 24 * 3600)  # 3 days in seconds
                seven_days_ago = current_time - (7 * 24 * 3600)  # 7 days in seconds
                
                trades_last_3_days = 0
                trades_last_7_days = 0
                days_active = 0
                
                if stats.last_seen:
                    if stats.last_seen > three_days_ago:
                        # Last trade was within 3 days - estimate trades_last_3_days
                        trades_last_3_days = min(stats.total_trades, 10)
                        days_active = 1
                    elif stats.last_seen > seven_days_ago:
                        # Last trade was within 7 days
                        days_active = 1
                
                # For API whales: use total_trades as proxy for trades_last_7_days
                # High total_trades from API indicates active trading
                if stats.total_trades >= 10:
                    # Whale with 10+ trades is likely active in last 7 days
                    trades_last_7_days = min(stats.total_trades, 20)
                    if days_active == 0:
                        days_active = 1
                
                # Calculate volume: use API value if available, otherwise estimate from avg_size * trades
                # This handles cases where API returns 0 volume but has avg_trade_size
                if stats.total_volume_usd > 0:
                    total_volume = stats.total_volume_usd
                else:
                    # Estimate volume from avg_trade_size and total_trades
                    total_volume = stats.avg_trade_size_usd * Decimal(stats.total_trades)
                
                whale = DetectedWhale(
                    wallet_address=address.lower(),
                    first_seen=stats.last_seen if stats.last_seen else time.time(),
                    total_trades=stats.total_trades,
                    total_volume=total_volume,
                    avg_trade_size=stats.avg_trade_size_usd,
                    trades_last_3_days=trades_last_3_days,
                    trades_last_7_days=trades_last_7_days,
                    days_active=days_active,
                    name=stats.name or "",
                )
                
                # Calculate risk_score for Polymarket API whales (required for qualification)
                # Convert timestamp (int) to datetime as required by calculate_risk_score
                last_active_dt = datetime.fromtimestamp(stats.last_seen) if stats.last_seen else None
                whale.risk_score = calculate_risk_score(
                    total_trades=whale.total_trades,
                    avg_trade_size=whale.avg_trade_size,
                    total_volume=whale.total_volume,
                    trades_per_day=Decimal(whale.daily_trades) if whale.daily_trades > 0 else Decimal("1"),
                    last_active=last_active_dt,
                )
                
                # Calculate dual-path qualification
                whale.qualification_path = self._calculate_qualification_path(
                    total_trades=whale.total_trades,
                    total_volume_usd=whale.total_volume,
                    avg_trade_size_usd=whale.avg_trade_size,
                    trades_last_7_days=whale.trades_last_7_days,
                    days_active=whale.days_active,
                    risk_score=whale.risk_score,
                )

                if stats.total_trades >= self.config.min_trades_for_quality:
                    self._detected_whales[address.lower()] = whale
                    await self._save_whale_to_db(whale)
                    
                    if not is_known:
                        self._known_whales.add(address.lower())
                        new_whales += 1
                        logger.info(
                            "polymarket_new_whale",
                            address=address[:10],
                            total_trades=stats.total_trades,
                            volume_usd=str(stats.total_volume_usd),
                        )
                    else:
                        logger.info(
                            "whale_updated",
                            address=address[:10],
                            total_trades=stats.total_trades,
                            volume_usd=str(stats.total_volume_usd),
                        )

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
