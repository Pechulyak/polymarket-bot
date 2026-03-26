# -*- coding: utf-8 -*-
"""Whale Poller - Tiered polling system for ongoing whale monitoring.

Manages periodic fetching of whale trades at different frequencies based on tier:
- HOT: every 4 hours (active in last 7 days)
- WARM: once daily (active 7-30 days ago)
- COLD: not polled (inactive > 30 days)

Example:
    >>> import asyncio
    >>> from src.research.whale_poller import WhalePoller
    >>> from src.research.polymarket_data_client import PolymarketDataClient
    >>>
    >>> async def main():
    ...     client = PolymarketDataClient()
    ...     poller = WhalePoller(db_pool, client, config)
    ...     await poller.start()
    ...
    >>> asyncio.run(main())
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import asyncpg
import structlog

from src.research.polymarket_data_client import PolymarketDataClient, TradeWithAddress
from src.research.whale_tracker import WhaleTracker

logger = structlog.get_logger(__name__)


# Polling intervals
HOT_POLL_INTERVAL_SECONDS = 4 * 60 * 60  # 4 hours
WARM_POLL_INTERVAL_SECONDS = 24 * 60 * 60  # 24 hours
DOWNGRADE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60  # 24 hours


@dataclass
class WhaleTierInfo:
    """Whale information from database with tier details."""

    id: int
    wallet_address: str
    tier: Optional[str]
    last_targeted_fetch_at: Optional[datetime]
    days_active_7d: int
    last_active_at: Optional[datetime]


class WhalePoller:
    """Tiered polling system for ongoing whale trade monitoring.

    Manages periodic fetching of whale trades at different frequencies:
    - HOT: every 4 hours for whales active in last 7 days
    - WARM: once daily for whales active 7-30 days ago
    - COLD: not polled (inactive > 30 days), requires re-discovery

    Attributes:
        db_pool: asyncpg database connection pool
        polymarket_client: PolymarketDataClient for fetching trades
        whale_tracker: WhaleTracker for saving whale trades
        config: Configuration dict with optional overrides
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        polymarket_client: PolymarketDataClient,
        whale_tracker: WhaleTracker,
        config: Optional[dict] = None,
    ):
        """Initialize WhalePoller.

        Args:
            db_pool: asyncpg database connection pool
            polymarket_client: PolymarketDataClient instance
            whale_tracker: WhaleTracker instance for saving trades
            config: Optional config overrides
        """
        self.db_pool = db_pool
        self.client = polymarket_client
        self.whale_tracker = whale_tracker
        self.config = config or {}

        # Allow configurable intervals for testing
        self.hot_poll_interval = self.config.get(
            "hot_poll_interval", HOT_POLL_INTERVAL_SECONDS
        )
        self.warm_poll_interval = self.config.get(
            "warm_poll_interval", WARM_POLL_INTERVAL_SECONDS
        )
        self.downgrade_check_interval = self.config.get(
            "downgrade_check_interval", DOWNGRADE_CHECK_INTERVAL_SECONDS
        )

        logger.info(
            "whale_poller_initialized",
            hot_interval=self.hot_poll_interval,
            warm_interval=self.warm_poll_interval,
        )

    async def get_whales_by_tier(self, tier: str) -> List[WhaleTierInfo]:
        """Get whales by tier from database.

        Args:
            tier: Tier to query ('HOT', 'WARM', or 'COLD')

        Returns:
            List of WhaleTierInfo objects
        """
        query = """
            SELECT 
                id, 
                wallet_address, 
                tier, 
                last_targeted_fetch_at,
                days_active_7d,
                last_active_at
            FROM whales
            WHERE tier = $1
            ORDER BY last_targeted_fetch_at ASC NULLS FIRST
        """

        try:
            rows = await self.db_pool.fetch(query, tier)
            whales = [
                WhaleTierInfo(
                    id=row["id"],
                    wallet_address=row["wallet_address"],
                    tier=row["tier"],
                    last_targeted_fetch_at=row["last_targeted_fetch_at"],
                    days_active_7d=row["days_active_7d"] or 0,
                    last_active_at=row["last_active_at"],
                )
                for row in rows
            ]
            logger.info("whales_by_tier_fetched", tier=tier, count=len(whales))
            return whales

        except Exception as e:
            logger.error("get_whales_by_tier_failed", tier=tier, error=str(e))
            return []

    async def poll_whale(
        self, whale: WhaleTierInfo
    ) -> List[TradeWithAddress]:
        """Poll a specific whale for new trades.

        Uses last_targeted_fetch_at to fetch only incremental trades.

        Args:
            whale: WhaleTierInfo to poll

        Returns:
            List of new TradeWithAddress objects
        """
        try:
            # Fetch trades since last fetch
            since = whale.last_targeted_fetch_at
            if since:
                # Convert to Unix timestamp
                since_timestamp = int(since.timestamp())
            else:
                # No previous fetch - get recent trades (limit 100)
                since_timestamp = None

            # Fetch trader trades
            if since_timestamp:
                # Use the API - it will return all trades, we filter locally
                trades = await self.client.fetch_trader_trades(
                    whale.wallet_address, limit=500
                )

                # Filter to only trades after last_targeted_fetch_at
                filtered_trades = [
                    t
                    for t in trades
                    if datetime.fromtimestamp(t.timestamp) > since
                ]
            else:
                # First fetch - get recent trades
                trades = await self.client.fetch_trader_trades(
                    whale.wallet_address, limit=100
                )
                filtered_trades = trades

            logger.info(
                "whale_polled",
                whale_id=whale.id,
                address=whale.wallet_address[:10],
                total_trades=len(trades),
                new_trades=len(filtered_trades),
            )

            return filtered_trades

        except Exception as e:
            logger.error(
                "whale_poll_failed",
                whale_id=whale.id,
                error=str(e),
            )
            return []

    async def process_new_trades(
        self, whale_id: int, whale_address: str, trades: List[TradeWithAddress]
    ) -> int:
        """Process new trades: INSERT to whale_trades, UPDATE whale stats.

        Args:
            whale_id: Whale database ID
            whale_address: Whale wallet address
            trades: List of new trades to process

        Returns:
            Number of new trades saved
        """
        if not trades:
            return 0

        saved_count = 0

        for trade in trades:
            try:
                # Use WhaleTracker.save_whale_trade for INSERT
                # This uses SQLAlchemy but is synchronous - we'll wrap it
                await self._save_whale_trade(whale_id, trade)
                saved_count += 1

            except Exception as e:
                logger.warning(
                    "trade_save_failed",
                    whale_id=whale_id,
                    trade_id=trade.tx_hash[:20] if trade.tx_hash else "unknown",
                    error=str(e),
                )

        if saved_count > 0:
            # Update whale stats
            await self._update_whale_after_trades(
                whale_id=whale_id,
                num_trades=len(trades),
                latest_trade_time=datetime.fromtimestamp(
                    max(t.timestamp for t in trades)
                ),
            )

        logger.info(
            "new_trades_processed",
            whale_id=whale_id,
            saved=saved_count,
            total=len(trades),
        )

        return saved_count

    async def _save_whale_trade(
        self, whale_id: int, trade: TradeWithAddress
    ) -> None:
        """Save a single whale trade to database.

        Uses asyncpg directly to avoid blocking.

        Args:
            whale_id: Whale database ID
            trade: TradeWithAddress to save
        """
        # Parse timestamp
        trade_time = datetime.fromtimestamp(trade.timestamp)
        side = "buy" if trade.side.upper() == "BUY" else "sell"

        # Get market_category for the market
        market_category = None
        if trade.condition_id:
            from src.data.storage.market_category_cache import get_market_category
            market_category = await get_market_category(trade.condition_id)

        query = """
            INSERT INTO whale_trades (
                whale_id,
                wallet_address,
                market_id,
                market_title,
                side,
                size_usd,
                price,
                outcome,
                traded_at,
                source,
                market_category
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT DO NOTHING
        """

        await self.db_pool.execute(
            query,
            whale_id,
            trade.trader,
            trade.condition_id,
            trade.market_title,
            side,
            float(trade.size_usd),
            float(trade.price),
            trade.outcome,
            trade_time,
            "POLLER",  # Source indicates this came from tiered polling
            market_category,
        )

    async def _update_whale_after_trades(
        self, whale_id: int, num_trades: int, latest_trade_time: datetime
    ) -> None:
        """Update whale stats after receiving new trades.

        Args:
            whale_id: Whale database ID
            num_trades: Number of new trades
            latest_trade_time: Timestamp of latest trade
        """
        now = datetime.utcnow()

        # Calculate days_active_7d increment (simplified - increment by 1 if trade on new day)
        # In production, you'd calculate this more precisely

        query = """
            UPDATE whales
            SET 
                last_targeted_fetch_at = $1,
                last_active_at = $2,
                tier = COALESCE(tier, 'HOT'),
                days_active_7d = COALESCE(days_active_7d, 0),
                trades_count = trades_count + $3,
                updated_at = NOW()
            WHERE id = $4
        """

        await self.db_pool.execute(
            query, now, latest_trade_time, num_trades, whale_id
        )

        logger.debug(
            "whale_updated_after_trades",
            whale_id=whale_id,
            new_trades=num_trades,
            last_active=latest_trade_time.isoformat(),
        )

    async def check_tier_downgrade(self) -> None:
        """Check and downgrade whale tiers based on inactivity.

        Downgrade logic:
        - HOT → WARM: no new trades for 7 consecutive days
        - WARM → COLD: no new trades for 30 consecutive days

        This should run once daily.
        """
        now = datetime.utcnow()
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        # Check HOT whales with no activity for 7 days → demote to WARM
        hot_to_warm_query = """
            UPDATE whales
            SET tier = 'WARM', updated_at = NOW()
            WHERE tier = 'HOT'
              AND (last_targeted_fetch_at < $1 OR last_targeted_fetch_at IS NULL)
              AND (last_active_at < $1 OR last_active_at IS NULL)
            RETURNING id, wallet_address
        """

        hot_demoted = await self.db_pool.fetch(hot_to_warm_query, seven_days_ago)

        if hot_demoted:
            logger.info(
                "hot_whales_demoted_to_warm",
                count=len(hot_demoted),
                ids=[r["id"] for r in hot_demoted],
            )

        # Check WARM whales with no activity for 30 days → demote to COLD
        warm_to_cold_query = """
            UPDATE whales
            SET tier = 'COLD', updated_at = NOW()
            WHERE tier = 'WARM'
              AND (last_targeted_fetch_at < $1 OR last_targeted_fetch_at IS NULL)
              AND (last_active_at < $1 OR last_active_at IS NULL)
            RETURNING id, wallet_address
        """

        warm_demoted = await self.db_pool.fetch(warm_to_cold_query, thirty_days_ago)

        if warm_demoted:
            logger.info(
                "warm_whales_demoted_to_cold",
                count=len(warm_demoted),
                ids=[r["id"] for r in warm_demoted],
            )

        logger.info(
            "tier_downgrade_check_completed",
            hot_to_warm=len(hot_demoted),
            warm_to_cold=len(warm_demoted),
        )

    async def run_hot_polling(self) -> None:
        """Poll HOT whales every 4 hours.

        HOT criterion: last_targeted_fetch_at >= NOW() - 7 days
        """
        logger.info("starting_hot_polling_loop")

        while True:
            try:
                # Get HOT whales
                hot_whales = await self.get_whales_by_tier("HOT")

                if not hot_whales:
                    logger.debug("no_hot_whales_to_poll")
                else:
                    logger.info("polling_hot_whales", count=len(hot_whales))

                    for whale in hot_whales:
                        # Poll whale for new trades
                        trades = await self.poll_whale(whale)

                        if trades:
                            # Process and save new trades
                            await self.process_new_trades(
                                whale_id=whale.id,
                                whale_address=whale.wallet_address,
                                trades=trades,
                            )

                        # Small delay between whales to avoid rate limiting
                        await asyncio.sleep(0.5)

                logger.info("hot_polling_cycle_completed", whales_polled=len(hot_whales))

            except Exception as e:
                logger.error("hot_polling_error", error=str(e))

            # Wait before next cycle
            await asyncio.sleep(self.hot_poll_interval)

    async def run_warm_polling(self) -> None:
        """Poll WARM whales once daily.

        WARM criterion: 7d < last_targeted_fetch_at <= 30d
        """
        logger.info("starting_warm_polling_loop")

        while True:
            try:
                # Get WARM whales
                warm_whales = await self.get_whales_by_tier("WARM")

                if not warm_whales:
                    logger.debug("no_warm_whales_to_poll")
                else:
                    logger.info("polling_warm_whales", count=len(warm_whales))

                    for whale in warm_whales:
                        # Poll whale for new trades
                        trades = await self.poll_whale(whale)

                        if trades:
                            # If whale became active again, promote to HOT
                            await self._promote_if_active(whale, trades)

                            # Process and save new trades
                            await self.process_new_trades(
                                whale_id=whale.id,
                                whale_address=whale.wallet_address,
                                trades=trades,
                            )

                        # Small delay between whales
                        await asyncio.sleep(0.5)

                logger.info("warm_polling_cycle_completed", whales_polled=len(warm_whales))

            except Exception as e:
                logger.error("warm_polling_error", error=str(e))

            # Wait before next cycle (24 hours)
            await asyncio.sleep(self.warm_poll_interval)

    async def _promote_if_active(
        self, whale: WhaleTierInfo, trades: List[TradeWithAddress]
    ) -> None:
        """Promote whale to HOT if it received new trades.

        Args:
            whale: Whale being polled
            trades: New trades received
        """
        if not trades:
            return

        # If we got new trades, promote to HOT
        query = """
            UPDATE whales
            SET tier = 'HOT', updated_at = NOW()
            WHERE id = $1 AND COALESCE(tier, 'COLD') IN ('WARM', 'COLD')
        """

        result = await self.db_pool.execute(query, whale.id)

        if result == "UPDATE 1":
            logger.info(
                "whale_promoted_to_hot",
                whale_id=whale.id,
                new_trades=len(trades),
            )

    async def run_tier_downgrade_check(self) -> None:
        """Check for tier downgrades once daily.

        Runs daily to demote inactive whales:
        - HOT → WARM: no activity for 7 days
        - WARM → COLD: no activity for 30 days
        """
        logger.info("starting_tier_downgrade_check_loop")

        while True:
            try:
                await self.check_tier_downgrade()
                logger.info("tier_downgrade_check_completed")

            except Exception as e:
                logger.error("tier_downgrade_check_error", error=str(e))

            # Wait before next check (24 hours)
            await asyncio.sleep(self.downgrade_check_interval)

    async def start(self) -> None:
        """Start all polling loops concurrently.

        Launches:
        - Hot polling loop (every 4 hours)
        - Warm polling loop (every 24 hours)
        - Tier downgrade check (every 24 hours)
        """
        logger.info("starting_whale_poller")

        # Create tasks for all polling loops
        tasks = [
            asyncio.create_task(self.run_hot_polling()),
            asyncio.create_task(self.run_warm_polling()),
            asyncio.create_task(self.run_tier_downgrade_check()),
        ]

        # Wait for all tasks
        # This will run forever until cancelled
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("whale_poller_cancelled")
            # Cancel all tasks
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("whale_poller_stopped")


async def create_whale_poller(
    db_pool: asyncpg.Pool,
    config: Optional[dict] = None,
) -> WhalePoller:
    """Factory function to create WhalePoller with dependencies.

    Args:
        db_pool: asyncpg database connection pool
        config: Optional config overrides

    Returns:
        Configured WhalePoller instance
    """
    # Create Polymarket Data client
    client = PolymarketDataClient()

    # Create WhaleTracker (for save_whale_trade compatibility)
    # Note: We're using asyncpg directly in the poller for performance
    whale_tracker = WhaleTracker()

    logger.info("whale_poller_created")

    return WhalePoller(
        db_pool=db_pool,
        polymarket_client=client,
        whale_tracker=whale_tracker,
        config=config,
    )