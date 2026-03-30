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

from src.data.storage.market_category_cache import get_market_category
from src.data.storage.market_title_cache import get_market_title
from src.research.polymarket_data_client import (
    PolymarketDataClient,
)
from src.research.whale_trade_writer import save_whale_trade
from src.research.whale_tracker import calculate_risk_score

logger = structlog.get_logger(__name__)


def normalize_outcome(
    outcome: Optional[str], 
    outcome_index: Optional[int] = None,
    market_type: Optional[str] = None
) -> Optional[str]:
    """Normalize Polymarket API outcome to standard format.
    
    Polymarket API can return:
    - Binary: "Yes"/"No" 
    - Up/Down: "Up"/"Down"
    - Over/Under: "Over"/"Under"
    - Team vs Team: team names (e.g., "BNK FEARX", "Team Secret Whales")
    - outcomeIndex: 0 (Yes/Up/Over/First) or 1 (No/Down/Under/Second)
    
    Mapping based on market_type:
    - "binary": Yes/No -> Yes/No
    - "up_down": Up/Down -> Yes/No (Up=Yes, Down=No)
    - "over_under": Over/Under -> Yes/No (Over=Yes, Under=No)
    - "team": outcomeIndex 0 -> "Team1", 1 -> "Team2"
    - None (auto-detect): Try to detect from outcome string
    
    Args:
        outcome: Raw outcome string from API
        outcome_index: Optional outcomeIndex (0 = first, 1 = second)
        market_type: Optional hint about market type ("binary", "up_down", "over_under", "team")
    
    Returns:
        Normalized outcome: "Yes", "No", "Team1", "Team2", or original
    """
    # Use outcome_index if provided (most reliable)
    if outcome_index is not None:
        if market_type == "team":
            return "Team1" if outcome_index == 0 else "Team2"
        else:
            # Default: 0 = Yes, 1 = No
            return "Yes" if outcome_index == 0 else "No"
    
    if outcome:
        outcome_lower = outcome.lower()
        if outcome_lower in ("yes", "no"):
            return outcome  # Already normalized
        elif outcome_lower in ("up", "down"):
            # Convert Up->Yes, Down->No
            return "Yes" if outcome_lower == "up" else "No"
        elif outcome_lower in ("over", "under"):
            # Convert Over->Yes, Under->No (for O/U markets)
            return "Yes" if outcome_lower == "over" else "No"
        else:
            # For unknown outcomes (team names, etc.), return as-is
            # Caller should pass market_type="team" for proper Team1/Team2 mapping
            return outcome
    
    return None


# Keep backward compatibility alias
convert_outcome_to_yes_no = normalize_outcome


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
    """

    trader: str
    market_id: str
    side: str
    size_usd: Decimal
    price: Decimal
    timestamp: float


@dataclass
class DetectedWhale:
    """Represents a whale identified by the detector.

    TRD-419 MIGRATION NOTES:
    - NEW: qualification_status replaces status (discovered/candidate/tracked/qualified)
    - NEW: days_active_7d / days_active_30d for activity windows
    - NEW: trades_count as canonical field (alias for total_trades)
    - DEPRECATED: status, days_active, win_rate, total_profit_usd, qualification_path
      (kept for backward compatibility, will be removed in next cleanup)

    Attributes:
        wallet_address: Whale wallet address
        first_seen: When whale was first detected
        total_trades: Total number of trades observed
        total_volume: Total trading volume
        avg_trade_size: Average trade size
        win_count: Number of winning trades (DEPRECATED - API doesn't provide)
        loss_count: Number of losing trades (DEPRECATED - API doesn't provide)
        win_rate: Win rate as decimal (DEPRECATED - always 0)
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
    win_rate: Decimal = Decimal("0")  # DEPRECATED - always 0, API doesn't provide
    daily_trades: int = 0
    risk_score: int = 5
    is_quality: bool = False
    # DEPRECATED FIELDS (TRD-419 - to be removed in next cleanup):
    status: str = "discovered"  # DEPRECATED -> use qualification_status
    trades_last_3_days: int = 0
    trades_last_7_days: int = 0  # DEPRECATED -> use trades_last_7_days from DB
    days_active: int = 0  # DEPRECATED -> use days_active_7d
    name: str = ""  # Trader's name from Polymarket profile
    qualification_path: Optional[str] = None  # DEPRECATED -> redundant with qualification_status

    # NEW FIELDS (TRD-419 - activity-based):
    qualification_status: str = "discovered"  # Replaces status
    days_active_7d: int = 0  # Active days in last 7 days
    days_active_30d: int = 0  # Active days in last 30 days


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

        # TRD-420 Bootstrap: Fetch initial history for existing whales
        # This assigns tier to 38 existing whales that have initial_history_fetched = NULL
        if self.polymarket_client:
            try:
                await self._bootstrap_existing_whales()
            except Exception as e:
                logger.error("bootstrap_failed_non_fatal", error=str(e))
                logger.info("continuing_without_bootstrap")

        if self.polymarket_client:
            await self.start_polymarket_polling()

        # TRD-420 v2: Independent copy polling loop
        self._copy_poll_task = asyncio.create_task(self._copy_poll_loop())

        logger.info("whale_detector_started")

    async def stop(self) -> None:
        """Stop the whale detector."""
        self._running = False

        await self.stop_polymarket_polling()

        # TRD-420 v2: Cancel independent copy polling loop
        if hasattr(self, '_copy_poll_task') and self._copy_poll_task:
            self._copy_poll_task.cancel()
            try:
                await self._copy_poll_task
            except asyncio.CancelledError:
                pass
            self._copy_poll_task = None

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
            # TRD-419: Use qualification_status instead of deprecated is_active
            # Whales are considered "active" if they have qualified status
            query = text("""
                SELECT wallet_address FROM whales
                WHERE qualification_status IN ('qualified', 'ranked', 'tracked')
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

    async def _bootstrap_existing_whales(self) -> None:
        """TRD-420 Bootstrap: Fetch initial history for existing whales.
        
        Called at startup to assign tier to whales that have:
        - initial_history_fetched = FALSE
        - OR initial_history_fetched IS NULL
        
        This ensures all existing whales get tier assigned (HOT/WARM/COLD)
        based on their last trading activity from Polymarket API.
        """
        await self._ensure_database()
        if not self._Session:
            logger.warning("bootstrap_no_session")
            return

        session = self._Session()
        try:
            # Get whales that need initial history fetched
            query = text("""
                SELECT wallet_address 
                FROM whales 
                WHERE initial_history_fetched IS NULL 
                   OR initial_history_fetched = FALSE
            """)
            result = session.execute(query)
            addresses = [row[0] for row in result]
            
            if not addresses:
                logger.info("bootstrap_no_whales_needed")
                return
                
            logger.info("bootstrap_starting", whales_count=len(addresses))
            
            # Fetch history for each whale (non-blocking, sequential)
            for address in addresses:
                try:
                    await asyncio.wait_for(
                        self._fetch_initial_history(address),
                        timeout=30.0
                    )
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(0.5)
                except asyncio.TimeoutError:
                    logger.warning("bootstrap_whale_timeout", address=address[:10])
                    continue
                except Exception as e:
                    logger.error("bootstrap_whale_failed", address=address[:10], error=str(e))
                    continue
            
            logger.info("bootstrap_complete", whales_processed=len(addresses))
            
        except Exception as e:
            logger.error("bootstrap_failed", error=str(e))
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
    ) -> Optional[DetectedWhale]:
        """Process a trade and detect if trader is a whale.

        Args:
            trader: Trader wallet address
            market_id: Market identifier
            side: Trade side ("buy" or "sell")
            size_usd: Trade size in USD
            price: Execution price
            timestamp: Trade timestamp (default: now)

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

        # win_count/loss_count/win_rate REMOVED (ARC-503) - API does not provide is_winner
        # These fields are now deprecated and always 0
        whale.win_count = 0
        whale.loss_count = 0

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
        
        # Set status based on qualification (TRD-419: use qualification_status)
        if is_qualified:
            whale.qualification_status = "qualified"
            whale.status = "qualified"  # Legacy - for backward compat
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
            whale.qualification_status = "discovered"
            whale.status = "discovered"  # Legacy - for backward compat
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
                    # Update whale with new qualification (ARC-501: removed deprecated columns)
                    update_query = text("""
                        UPDATE whales
                        SET qualification_status = CASE
                            WHEN :qualification_path IS NOT NULL THEN 'qualified'
                            ELSE qualification_status
                        END,
                            trades_last_7_days = :trades_last_7_days,
                            days_active_7d = LEAST(:days_active, 7),
                            days_active_30d = LEAST(:days_active, 30),
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
            
            # TRD-419: Update both legacy days_active and new days_active_7d/30d
            # days_active is kept for backward compat, days_active_7d is the new canonical
            update_days = text("""
                UPDATE whales w
                SET days_active = t.days,
                    days_active_7d = LEAST(t.days_7d, t.days),  -- 7d window
                    days_active_30d = LEAST(t.days_30d, t.days),  -- 30d window
                    last_active_at = NOW(),
                    updated_at = NOW()
                FROM (
                    SELECT
                        wallet_address,
                        COUNT(DISTINCT DATE(traded_at)) as days,
                        COUNT(DISTINCT DATE(traded_at)) FILTER (WHERE traded_at >= NOW() - INTERVAL '7 days') as days_7d,
                        COUNT(DISTINCT DATE(traded_at)) FILTER (WHERE traded_at >= NOW() - INTERVAL '30 days') as days_30d
                    FROM whale_trades
                    GROUP BY wallet_address
                ) t
                WHERE LOWER(w.wallet_address) = LOWER(t.wallet_address)
                AND (w.days_active != t.days OR w.days_active_7d IS NULL OR w.days_active_30d IS NULL)
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
            # TRD-419: Use new activity-based fields
            # qualification_status replaces status
            # days_active_7d replaces days_active (for 7-day window logic)
            # ARC-501: Removed deprecated columns (total_profit_usd, qualification_path, status, days_active)
            query = text("""
                INSERT INTO whales (
                    wallet_address, total_trades,
                    total_volume_usd, avg_trade_size_usd, last_active_at, risk_score,
                    qualification_status, trades_last_3_days, trades_last_7_days,
                    days_active_7d, days_active_30d,
                    source_new, updated_at, notes
                ) VALUES (
                    :wallet_address, :total_trades,
                    :total_volume, :avg_trade_size, NOW(), :risk_score,
                    :qualification_status, :trades_last_3_days, :trades_last_7_days,
                    :days_active_7d, :days_active_30d,
                    'auto_detected', NOW(), :notes
                )
                ON CONFLICT (wallet_address) DO UPDATE SET
                    total_trades = EXCLUDED.total_trades,
                    total_volume_usd = EXCLUDED.total_volume_usd,
                    avg_trade_size_usd = EXCLUDED.avg_trade_size_usd,
                    risk_score = EXCLUDED.risk_score,
                    qualification_status = EXCLUDED.qualification_status,
                    trades_last_3_days = EXCLUDED.trades_last_3_days,
                    trades_last_7_days = EXCLUDED.trades_last_7_days,
                    days_active_7d = EXCLUDED.days_active_7d,
                    days_active_30d = EXCLUDED.days_active_30d,
                    last_active_at = NOW(),
                    updated_at = NOW(),
                    notes = EXCLUDED.notes
            """)
            session.execute(
                query,
                {
                    "wallet_address": whale.wallet_address,
                    "total_trades": whale.total_trades,
                    "total_volume": float(whale.total_volume),
                    "avg_trade_size": float(whale.avg_trade_size),
                    "risk_score": whale.risk_score,
                    "qualification_status": whale.qualification_status,
                    "trades_last_3_days": whale.trades_last_3_days,
                    "trades_last_7_days": whale.trades_last_7_days,
                    "days_active_7d": whale.days_active_7d,
                    "days_active_30d": whale.days_active_30d,
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

        # TRD-420: Fetch initial history for new whales
        # Check if initial_history_fetched is FALSE or NULL
        # Use asyncio.create_task to NOT block the main loop
        if self.polymarket_client:
            # Check if we need to fetch initial history (non-blocking check)
            asyncio.create_task(self._fetch_initial_history(whale.wallet_address))

    async def _fetch_initial_history(self, address: str) -> None:
        """
        Разовый API-запрос при первом обнаружении адреса.
        Агрегирует историю в памяти → пишет только в whales.
        НЕ пишет в whale_trades.

        Args:
            address: Whale wallet address to fetch history for
        """
        if not self.polymarket_client:
            logger.debug("fetch_initial_history_no_client", address=address[:10])
            return

        await self._ensure_database()
        if not self._Session:
            logger.warning("fetch_initial_history_no_session", address=address[:10])
            return

        # Check if already fetched
        session = self._Session()
        try:
            check_query = text("""
                SELECT initial_history_fetched, last_seen_in_feed
                FROM whales
                WHERE LOWER(wallet_address) = LOWER(:address)
            """)
            result = session.execute(check_query, {"address": address})
            row = result.fetchone()

            if row and row[0] is True:
                logger.debug("initial_history_already_fetched", address=address[:10])
                session.close()
                return

        except Exception as e:
            logger.error("check_initial_history_failed", error=str(e), address=address[:10])
            session.close()
            return
        finally:
            session.close()

        # Fetch trader history from Polymarket API
        try:
            logger.info("fetching_initial_history", address=address[:10])
            trades = await self.polymarket_client.fetch_trader_trades(address, limit=500)

            if not trades:
                logger.info("no_trades_for_history", address=address[:10])
                return

            # Aggregate in memory
            total_volume = Decimal("0")
            trade_count = len(trades)
            timestamps = []

            for t in trades:
                total_volume += t.size_usd
                timestamps.append(t.timestamp)

            # Calculate unique trading days
            unique_days = len(set(
                datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                for ts in timestamps
            ))

            # Calculate average trade size
            avg_size = total_volume / Decimal(trade_count) if trade_count > 0 else Decimal("0")

            # Determine last_seen timestamp
            last_seen_ts = max(timestamps) if timestamps else None
            last_seen_dt = datetime.fromtimestamp(last_seen_ts) if last_seen_ts else None

            # Determine tier based on days since last seen
            tier = "COLD"  # Default
            if last_seen_ts:
                days_since_last = (time.time() - last_seen_ts) / 86400
                if days_since_last <= 1:
                    tier = "HOT"
                elif days_since_last <= 7:
                    tier = "WARM"
                # else: tier remains "COLD"

            # Determine last_qualified_at (不使用 qualification_path - удалён в ARC-501)
            last_qualified_at = datetime.now() if (tier == "HOT" and total_volume >= Decimal("500")) or (tier in ("WARM", "COLD") and total_volume >= Decimal("10000")) else None
            
            # ARC-501: Removed deprecated columns from UPDATE
            update_query = text("""
                UPDATE whales
                SET initial_history_fetched = TRUE,
                    history_trade_count = :trade_count,
                    history_volume_usd = :total_volume,
                    tier = :tier,
                    last_seen_in_feed = :last_seen,
                    last_targeted_fetch_at = NOW(),
                    source_new = 'auto_detected',
                    last_qualified_at = :last_qualified_at,
                    updated_at = NOW()
                WHERE LOWER(wallet_address) = LOWER(:address)
            """)
            session.execute(update_query, {
                "trade_count": trade_count,
                "total_volume": float(total_volume),
                "tier": tier,
                "last_seen": last_seen_dt,
                "last_qualified_at": last_qualified_at,
                "address": address,
            })
            session.commit()

            logger.info(
                "initial_history_fetched",
                address=address[:10],
                trade_count=trade_count,
                total_volume=float(total_volume),
                unique_days=unique_days,
                avg_size=float(avg_size),
                tier=tier,
            )

        except Exception as e:
            logger.error("update_whale_history_failed", error=str(e), address=address[:10])
            if session.is_active:
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
        """Save trade to whale_trades table using unified save_whale_trade method.

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
        # Ensure async engine exists
        if not hasattr(self, '_async_engine') or self._async_engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine
            async_db_url = self.database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://") if "postgresql+" in self.database_url else self.database_url.replace("postgresql://", "postgresql+asyncpg://")
            self._async_engine = create_async_engine(async_db_url, pool_pre_ping=True)

        # Get market category
        market_category = await get_market_category(market_id)

        # Create async session
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker
        async_session_maker = sessionmaker(
            self._async_engine, class_=AsyncSession, expire_on_commit=False
        )

        trader_lower = trader.lower()

        async with async_session_maker() as session:
            try:
                await save_whale_trade(
                    session=session,
                    wallet_address=trader_lower,
                    market_id=market_id,
                    side=side,
                    size_usd=size_usd,
                    price=price,
                    outcome=outcome,
                    market_title=market_title,
                    market_category=market_category,
                    tx_hash=tx_hash,
                    source=source,
                )
                logger.info(
                    "whale_trade_saved",
                    wallet_address=trader_lower[:10],
                    market_id=market_id[:20] if market_id else "unknown",
                    side=side,
                    size_usd=str(size_usd),
                )
                return True
            except Exception as e:
                # Check if it's a duplicate (deduplication in save_whale_trade)
                if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                    logger.debug("trade_duplicate_skip", tx_hash=tx_hash[:16] if tx_hash else None)
                    return False
                logger.warning("trade_save_error", error=str(e), trader=trader_lower[:10] if trader_lower else "unknown")
                return False

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

    async def _copy_poll_loop(self) -> None:
        """TRD-420 v2: Independent loop for paper/tracked whale polling.
        Runs separately from _polymarket_poll_loop() to ensure it never
        gets blocked by main loop issues.
        """
        logger.info("copy_poll_loop_started")
        while self._running:
            try:
                await asyncio.wait_for(
                    self._fetch_paper_whale_trades(),
                    timeout=120
                )
            except asyncio.TimeoutError:
                logger.error("paper_fetch_timeout", timeout_sec=120)
            except Exception as e:
                logger.error("paper_fetch_error", error=str(e))
            
            await asyncio.sleep(30)
            
            try:
                await asyncio.wait_for(
                    self._fetch_tracked_whale_trades(),
                    timeout=300
                )
            except asyncio.TimeoutError:
                logger.error("tracked_fetch_timeout", timeout_sec=300)
            except Exception as e:
                logger.error("tracked_fetch_error", error=str(e))
            
            await asyncio.sleep(270)  # 30 + 270 = 300 sec (5 min) until next cycle
        logger.info("copy_poll_loop_stopped")

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
            
            # TRD-423: Re-enabled - Trade ingestion fixed
            # Save trades to whale_trades table for analysis
            # DEBUG: Log first few trades to diagnose filtering
            logger.warning("DEBUG_TRADES_RECEIVED", 
                count=len(trades),
                min_size_used=str(min_size),
                sample_trades=[
                    {
                        "trader": str(t.trader)[:10] if t.trader else "NONE",
                        "condition_id": str(t.condition_id)[:20] if t.condition_id else "NONE",
                        "size_usd": str(t.size_usd),
                        "tx_hash": str(t.tx_hash)[:16] if t.tx_hash else "NONE",
                    }
                    for t in trades[:3]
                ] if trades else []
            )
            
            for trade in trades:
                try:
                    # Determine side from trade
                    side = "buy" if trade.side.upper() == "BUY" else "sell"
                    
                    # Get market_id from condition_id - guard against empty
                    market_id = trade.condition_id or ""
                    if not market_id:
                        logger.warning("trade_skip_empty_market_id", 
                                     trader=trade.trader[:10] if trade.trader else "unknown")
                        continue
                    
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
                    logger.warning("trade_save_error", error=str(e), trader=trade.trader[:10] if trade.trader else "unknown")
            
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

    async def _fetch_paper_whale_trades(self) -> None:
        """Fetch recent trades for whales with copy_status='paper'.

        Targeted per-wallet fetch to ensure paper-trade pipeline
        receives all trades from tracked whales.
        Uses existing save_trade_to_db with tx_hash dedup.

        Runs every 30 seconds as part of _polymarket_poll_loop.
        """
        await self._ensure_database()
        if not self._Session:
            logger.warning("paper_whale_fetch_no_session")
            return

        if not self.polymarket_client:
            logger.warning("paper_whale_fetch_no_client")
            return

        session = self._Session()
        try:
            # Step 1: Get whales with copy_status='paper'
            query = text("""
                SELECT wallet_address FROM whales
                WHERE copy_status = 'paper'
            """)
            result = session.execute(query)
            paper_whales = [row[0] for row in result]

            if not paper_whales:
                logger.debug("paper_whale_fetch_no_paper_whales")
                session.close()
                return

            logger.info(
                "paper_whale_fetch_cycle_start",
                paper_whales_count=len(paper_whales),
            )
            session.close()

            # Step 2: Fetch trades for each paper whale
            new_trades_count = 0
            duplicates_count = 0

            for address in paper_whales:
                try:
                    # Rate limit: 0.3s between requests
                    await asyncio.sleep(0.3)

                    # Fetch recent trades for this whale
                    trades = await self.polymarket_client.fetch_trader_trades(
                        address, limit=50
                    )

                    for trade in trades:
                        try:
                            # Map API fields to save_trade_to_db parameters:
                            # - API size = number of shares (tokens), NOT USD
                            # - size_usd = size * price
                            size_shares = Decimal(str(trade.size))
                            trade_price = Decimal(str(trade.price))
                            size_usd = size_shares * trade_price

                            # Normalize outcome: outcomeIndex 0 = Yes, 1 = No
                            # Use outcomeIndex for reliable binary mapping
                            outcome_index = None
                            if hasattr(trade, 'outcome_index') and trade.outcome_index is not None:
                                outcome_index = trade.outcome_index

                            normalized_outcome = normalize_outcome(
                                outcome=trade.outcome,
                                outcome_index=outcome_index,
                            )

                            # Save trade to db with dedup by tx_hash
                            saved = await self.save_trade_to_db(
                                trader=trade.trader.lower(),
                                market_id=trade.condition_id,
                                side="buy" if trade.side.upper() == "BUY" else "sell",
                                size_usd=size_usd,
                                price=trade_price,
                                timestamp=float(trade.timestamp),
                                tx_hash=trade.tx_hash,
                                market_title=trade.market_title,
                                source="PAPER_TRACK",  # Distinguish from BACKFILL/REALTIME
                                outcome=normalized_outcome,
                            )

                            if saved:
                                new_trades_count += 1
                            else:
                                duplicates_count += 1

                        except Exception as e:
                            logger.warning(
                                "paper_whale_trade_save_error",
                                error=str(e),
                                trader=trade.trader[:10] if trade.trader else "unknown",
                            )
                            continue

                except Exception as e:
                    logger.warning(
                        "paper_whale_fetch_error",
                        address=address[:10],
                        error=str(e),
                    )
                    continue

            logger.info(
                "paper_whale_fetch_cycle_complete",
                paper_whales_count=len(paper_whales),
                new_trades=new_trades_count,
                duplicates=duplicates_count,
            )

        except Exception as e:
            logger.error("paper_whale_fetch_failed", error=str(e))

    async def _fetch_tracked_whale_trades(self) -> None:
        """Fetch recent trades for whales with copy_status='tracked'.

        Targeted per-wallet fetch to collect data for P&L analysis.
        Does NOT create paper_trades (trigger only fires for copy_status='paper').

        Runs every 5 minutes as part of _polymarket_poll_loop.
        """
        await self._ensure_database()
        if not self._Session:
            logger.warning("tracked_whale_fetch_no_session")
            return

        if not self.polymarket_client:
            logger.warning("tracked_whale_fetch_no_client")
            return

        session = self._Session()
        try:
            # Step 1: Get whales with copy_status='tracked'
            query = text("""
                SELECT wallet_address FROM whales
                WHERE copy_status = 'tracked'
            """)
            result = session.execute(query)
            tracked_whales = [row[0] for row in result]

            if not tracked_whales:
                logger.debug("tracked_whale_fetch_no_tracked_whales")
                session.close()
                return

            logger.info(
                "tracked_whale_fetch_cycle_start",
                tracked_whales_count=len(tracked_whales),
            )
            session.close()

            # Step 2: Fetch trades for each tracked whale
            new_trades_count = 0
            duplicates_count = 0

            for address in tracked_whales:
                try:
                    # Rate limit: 0.3s between requests
                    await asyncio.sleep(0.3)

                    # Fetch recent trades for this whale
                    trades = await self.polymarket_client.fetch_trader_trades(
                        address, limit=50
                    )

                    for trade in trades:
                        try:
                            # Map API fields to save_trade_to_db parameters:
                            # - API size = number of shares (tokens), NOT USD
                            # - size_usd = size * price
                            size_shares = Decimal(str(trade.size))
                            trade_price = Decimal(str(trade.price))
                            size_usd = size_shares * trade_price

                            # Normalize outcome: outcomeIndex 0 = Yes, 1 = No
                            # Use outcomeIndex for reliable binary mapping
                            outcome_index = None
                            if hasattr(trade, 'outcome_index') and trade.outcome_index is not None:
                                outcome_index = trade.outcome_index

                            normalized_outcome = normalize_outcome(
                                outcome=trade.outcome,
                                outcome_index=outcome_index,
                            )

                            # Save trade to db with dedup by tx_hash
                            saved = await self.save_trade_to_db(
                                trader=trade.trader.lower(),
                                market_id=trade.condition_id,
                                side="buy" if trade.side.upper() == "BUY" else "sell",
                                size_usd=size_usd,
                                price=trade_price,
                                timestamp=float(trade.timestamp),
                                tx_hash=trade.tx_hash,
                                market_title=trade.market_title,
                                source="TRACKED",  # Distinguish from BACKFILL/PAPER_TRACK
                                outcome=normalized_outcome,
                            )

                            if saved:
                                new_trades_count += 1
                            else:
                                duplicates_count += 1

                        except Exception as e:
                            logger.warning(
                                "tracked_whale_trade_save_error",
                                error=str(e),
                                trader=trade.trader[:10] if trade.trader else "unknown",
                            )
                            continue

                except Exception as e:
                    logger.warning(
                        "tracked_whale_fetch_error",
                        address=address[:10],
                        error=str(e),
                    )
                    continue

            logger.info(
                "tracked_whale_fetch_cycle_complete",
                tracked_whales_count=len(tracked_whales),
                new_trades=new_trades_count,
                duplicates=duplicates_count,
            )

        except Exception as e:
            logger.error("tracked_whale_fetch_failed", error=str(e))

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
        # Get all qualified whales (TRD-419: use qualification_status)
        qualified = [
            w for w in self._detected_whales.values()
            if w.qualification_status in ("qualified", "ranked")
            or w.status in ("qualified", "ranked")  # Legacy compat
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
        
        # Update status to 'ranked' for top N (TRD-419: also update qualification_status)
        for i, whale in enumerate(ranked[:limit]):
            if whale.qualification_status != "ranked":
                whale.qualification_status = "ranked"
                whale.status = "ranked"  # Legacy compat
        
        return ranked[:limit]
