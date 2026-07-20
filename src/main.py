# -*- coding: utf-8 -*-
"""Main entry point for trading bot with whale copy trading."""

import asyncio
import argparse
import os
from datetime import datetime
from decimal import Decimal
from typing import Optional, Set

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.monitoring import get_logger
from src.monitoring.notification_worker import NotificationWorker
from src.research.whale_tracker import WhaleTracker

logger = get_logger(__name__)


# DEPRECATED: Phase 2B — replaced by DB trigger deduplication
# Cache for processed trade IDs to avoid duplicates within same session
# _processed_trade_ids: Set[str] = set()


# DEPRECATED: Phase 2B — replaced by DB trigger + materialized view (Phase 4)
def _check_trade_exists(database_url: str, opportunity_id: str) -> bool:
    """DEPRECATED: Phase 2B — no longer used.

    Check if a trade already exists in trades by opportunity_id.
    
    Uses opportunity_id for exact match - each paper_trade converts to exactly one trade.
    
    Args:
        database_url: PostgreSQL connection URL
        opportunity_id: The opportunity_id to check
    
    Returns:
        True if trade already exists, False otherwise
    """
    # engine = create_engine(database_url)
    # Session = sessionmaker(bind=engine)
    # session = Session()
    # try:
    #     # Check for existing trade by opportunity_id
    #     query = text("""
    #         SELECT COUNT(*) FROM trades 
    #         WHERE opportunity_id = :opportunity_id
    #           AND exchange = 'VIRTUAL'
    #     """)
    #     result = session.execute(query, {"opportunity_id": opportunity_id})
    #     count = result.scalar()
    #     return count > 0
    # except Exception as e:
    #     logger.warning("trade_existence_check_failed", error=str(e))
    #     return False
    # finally:
    #     session.close()
    pass


# DEPRECATED: Phase 2B — replaced by DB trigger + materialized view (Phase 4)
def _get_pending_paper_trades(database_url: str, limit: int = 10) -> list:
    """DEPRECATED: Phase 2B — no longer used.

    Get pending paper trades from paper_trades table.
    
    Reads from paper_trades table (filled by trigger from whale_trades).
    This ensures the proper pipeline: whale_trades -> trigger -> paper_trades -> trades.
    
    Filters out trades that are already executed (exist in trades table).
    
    Args:
        database_url: PostgreSQL connection URL
        limit: Maximum number of trades to return
    
    Returns:
        List of pending paper trades with market_id, side, size_usd, price, whale_address
    """
    # engine = create_engine(database_url)
    # Session = sessionmaker(bind=engine)
    # session = Session()
    # try:
    #     # Get trades from paper_trades that haven't been executed yet
    #     # Exclude trades that already exist in trades table (by market_id + whale_address + side)
    #     query = text("""
    #         SELECT 
    #             pt.id as paper_trade_id,
    #             pt.market_id,
    #             pt.side,
    #             COALESCE(pt.size_usd, pt.size) as size_usd,
    #             pt.price,
    #             pt.whale_address,
    #             pt.created_at,
    #             pt.kelly_size,
    #             pt.outcome
    #         FROM paper_trades pt
    #         WHERE pt.created_at > NOW() - INTERVAL '15 minutes'
    #           AND NOT EXISTS (
    #             SELECT 1 FROM trades t 
    #             WHERE t.opportunity_id = pt.id::text
    #               AND t.exchange = 'VIRTUAL'
    #         )
    #         ORDER BY pt.created_at DESC
    #         LIMIT :limit
    #     """)
    #     result = session.execute(query, {"limit": limit})
    #     trades = []
    #     for row in result:
    #         trades.append({
    #             "paper_trade_id": row[0],
    #             "market_id": row[1],
    #             "side": row[2],
    #             "size_usd": row[3],
    #             "price": row[4],
    #             "whale_address": row[5],
    #             "created_at": row[6],
    #             "kelly_size": row[7],  # Kelly-sized position (capped at 2% of bankroll)
    #             "outcome": row[8],  # YES/NO outcome
    #         })
    #     return trades
    # except Exception as e:
    #     logger.warning("get_pending_paper_trades_failed", error=str(e))
    #     return []
    # finally:
    #     session.close()
    pass


async def main():
    """Main trading loop with whale copy trading."""
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--bankroll", type=float, default=100.0, help="DEPRECATED: Use INITIAL_BANKROLL env var instead")
    parser.add_argument("--observation-mode", action="store_true", default=False)
    args = parser.parse_args()

    # DEPRECATED: Phase 2B — no longer affects execution (kept to avoid NameError in logs below)
    # BUG-602: Read initial bankroll from environment (not from args to avoid reset on restart)
    initial_bankroll = Decimal(os.getenv("INITIAL_BANKROLL", "1000"))

    # DEPRECATED: Phase 2B — no longer affects execution (kept to avoid NameError in logs below)
    # Whale Observation Mode: suspend execution/downstream layers
    # Active: whales, whale_trades, paper_trades
    # Suspended: downstream execution layers
    observation_mode = args.observation_mode or os.getenv("OBSERVATION_MODE", "").lower() == "true"

    logger.info(f"Starting bot in {args.mode} mode with INITIAL_BANKROLL=${initial_bankroll}")
    if observation_mode:
        logger.info("WHALE OBSERVATION MODE ENABLED - execution layers suspended")

    # Database URL
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:password@postgres:5432/polymarket"
    )

    # Initialize Notification Worker for Telegram alerts (skip in observation mode)
    notification_worker = None
    if not observation_mode:
        notification_worker = NotificationWorker(
            database_url=database_url,
            poll_interval=2.0,
        )

    # Initialize Whale Tracker
    whale_tracker = WhaleTracker(database_url=database_url)
    whale_tracker.set_database(database_url)
    
    # Load quality whales from database
    logger.info("Loading quality whales from database...")
    quality_whales = await whale_tracker.load_quality_whales(
        min_win_rate=Decimal("0.60"),
        min_trades=100,
        max_risk_score=6
    )
    logger.info(f"Loaded {len(quality_whales)} quality whales")
    
    whale_addresses = [w.wallet_address for w in quality_whales]
    logger.info(f"Whale addresses: {whale_addresses[:3]}...")

    # DEPRECATED: Phase 2B — replaced by DB trigger + materialized view (Phase 4)
    # Trading loop - fetch whale trades periodically
    # loop_count = 0
    # check_interval = 5  # Check every 5 seconds (for testing)
    # settlement_interval = 60  # Run settlement every 60 iterations (1 minute)
    # SYS-601-FIX: Disabled - duplicate of standalone roundtrip_builder container
    # roundtrip_interval = 900  # Run whale roundtrip reconstruction every 900 iterations (15 minutes)
    # roundtrip_settle_interval = 300  # Run roundtrip settlement every 300 iterations (5 minutes)

    try:
        # Start notification worker as background task (skip in observation mode)
        notification_task = None
        if notification_worker:
            notification_task = asyncio.create_task(notification_worker.start())
            logger.info("notification_worker_started")

        _heartbeat_logged = False
        while True:
            if not _heartbeat_logged:
                logger.info("Phase 2B: heartbeat-only mode (paper_trades via DB trigger, roundtrips via roundtrip_builder)")
                _heartbeat_logged = True

            # DEPRECATED: Phase 2B — all polling, execution, settlement disabled below

            await asyncio.sleep(1)

            # Write heartbeat file for healthcheck
            try:
                with open("/tmp/heartbeat", "w") as f:
                    f.write(datetime.now().isoformat())
            except Exception:
                pass  # Non-critical, don't fail the loop

    except KeyboardInterrupt:
        logger.info("Shutting down...")
        if notification_worker:
            notification_worker.stop()
        if notification_task:
            notification_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())