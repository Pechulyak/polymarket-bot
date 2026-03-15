# -*- coding: utf-8 -*-
"""Main entry point for trading bot with whale copy trading."""

import asyncio
import argparse
import os
from decimal import Decimal
from typing import Optional, Set

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.monitoring import get_logger
from src.monitoring.notification_worker import NotificationWorker
from src.research.whale_tracker import WhaleTracker
from src.strategy.virtual_bankroll import VirtualBankroll

logger = get_logger(__name__)


# Cache for processed trade IDs to avoid duplicates within same session
_processed_trade_ids: Set[str] = set()


def _check_trade_exists(database_url: str, market_id: str, whale_address: str, size: Decimal, price: Decimal) -> bool:
    """Check if a similar trade already exists in the trades table.
    
    Uses market_id + whale_source + size + price as composite key to detect duplicates.
    
    Args:
        database_url: PostgreSQL connection URL
        market_id: Market identifier
        whale_address: Source whale wallet address
        size: Trade size in USD
        price: Execution price
    
    Returns:
        True if trade already exists, False otherwise
    """
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        # Check for existing trade with same market, whale source, size, and price
        query = text("""
            SELECT COUNT(*) FROM trades 
            WHERE market_id = :market_id 
              AND whale_source = :whale_source
              AND size = :size 
              AND price = :price
              AND exchange = 'VIRTUAL'
        """)
        result = session.execute(query, {
            "market_id": market_id,
            "whale_source": whale_address,
            "size": float(size),
            "price": float(price),
        })
        count = result.scalar()
        return count > 0
    except Exception as e:
        logger.warning("trade_existence_check_failed", error=str(e))
        return False
    finally:
        session.close()


def _get_pending_paper_trades(database_url: str, limit: int = 10) -> list:
    """Get pending paper trades from paper_trades table.
    
    Reads from paper_trades table (filled by trigger from whale_trades).
    This ensures the proper pipeline: whale_trades -> trigger -> paper_trades -> trades.
    
    Filters out trades that are already executed (exist in trades table).
    
    Args:
        database_url: PostgreSQL connection URL
        limit: Maximum number of trades to return
    
    Returns:
        List of pending paper trades with market_id, side, size_usd, price, whale_address
    """
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        # Get trades from paper_trades that haven't been executed yet
        # Exclude trades that already exist in trades table (by market_id + whale_address + side)
        query = text("""
            SELECT 
                pt.id as paper_trade_id,
                pt.market_id,
                pt.side,
                COALESCE(pt.size_usd, pt.size) as size_usd,
                pt.price,
                pt.whale_address,
                pt.created_at,
                pt.kelly_size
            FROM paper_trades pt
            WHERE NOT EXISTS (
                SELECT 1 FROM trades t 
                WHERE t.market_id = pt.market_id 
                  AND t.whale_source = pt.whale_address
                  AND t.side = pt.side
                  AND t.exchange = 'VIRTUAL'
            )
            ORDER BY pt.created_at DESC
            LIMIT :limit
        """)
        result = session.execute(query, {"limit": limit})
        trades = []
        for row in result:
            trades.append({
                "paper_trade_id": row[0],
                "market_id": row[1],
                "side": row[2],
                "size_usd": row[3],
                "price": row[4],
                "whale_address": row[5],
                "created_at": row[6],
                "kelly_size": row[7],  # Kelly-sized position (capped at 2% of bankroll)
            })
        return trades
    except Exception as e:
        logger.warning("get_pending_paper_trades_failed", error=str(e))
        return []
    finally:
        session.close()


async def main():
    """Main trading loop with whale copy trading."""
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--bankroll", type=float, default=100.0)
    args = parser.parse_args()

    logger.info(f"Starting bot in {args.mode} mode with ${args.bankroll} bankroll")

    # Database URL
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:password@postgres:5432/polymarket"
    )

    # Initialize Notification Worker for Telegram alerts
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

    # Initialize Virtual Bankroll for paper trading
    virtual_bankroll = VirtualBankroll(
        initial_balance=Decimal(str(args.bankroll)),
        database_url=database_url
    )
    virtual_bankroll.set_database(database_url)
    logger.info(f"Virtual bankroll initialized: ${args.bankroll}")

    # Trading loop - fetch whale trades periodically
    loop_count = 0
    check_interval = 5  # Check every 5 seconds (for testing)
    
    try:
        # Start notification worker as background task
        notification_task = asyncio.create_task(notification_worker.start())
        logger.info("notification_worker_started")

        while True:
            loop_count += 1
            
            # Every check_interval iterations, fetch new trades from paper_trades
            # This ensures proper pipeline: whale_trades -> trigger -> paper_trades -> trades
            if loop_count % check_interval == 0:
                logger.info(f"Checking paper_trades for pending trades (loop {loop_count})...")
                
                # Read from paper_trades table (filled by trigger from whale_trades)
                pending_trades = _get_pending_paper_trades(database_url, limit=10)
                
                if pending_trades:
                    logger.info(f"Found {len(pending_trades)} pending paper trades")
                    
                    # Process each trade - execute via VirtualBankroll
                    for trade in pending_trades:
                        # Use Kelly-sized position (already calculated and capped at 2% of bankroll)
                        # kelly_size is in paper_trades table, calculated based on Kelly Criterion
                        trade_size = Decimal(str(trade['kelly_size'])) if trade.get('kelly_size') else Decimal(str(trade['size_usd']))
                        
                        logger.info(
                            f"  Trade: {trade['side']} ${trade_size:.2f} "
                            f"(kelly_size=${trade['kelly_size']:.2f}) "
                            f"at {trade['price']} on {trade['market_id'][:16]}... "
                            f"whale: {trade['whale_address'][:8] if trade['whale_address'] else 'unknown'}..."
                        )
                        
                        # DEFENSIVE: Skip zero-size trades
                        if trade_size <= Decimal("0"):
                            logger.warning(
                                f"  Skipping zero-size trade: {trade['market_id'][:16]}... "
                                f"(size={trade_size})"
                            )
                            continue
                        
                        whale_addr = trade['whale_address']
                        
                        # Execute paper trade via VirtualBankroll
                        try:
                            # DEDUPLICATION CHECK - skip if trade already exists
                            if _check_trade_exists(database_url, trade['market_id'], whale_addr, trade_size, Decimal(str(trade['price']))):
                                logger.info(
                                    f"  Skipping duplicate trade: {trade['market_id'][:16]}... "
                                    f"${trade_size:.2f} @ {trade['price']}"
                                )
                                continue
                            
                            fees = trade_size * Decimal("0.002")
                            gas = Decimal("1.50")
                            
                            # Generate opportunity_id from paper_trade_id
                            opportunity_id = f"paper_{trade['paper_trade_id']}"
                            
                            # Get market title from cache
                            from src.data.storage.market_title_cache import get_market_title
                            market_title = await get_market_title(trade['market_id'])
                            
                            result = await virtual_bankroll.execute_virtual_trade(
                                market_id=trade['market_id'],
                                side=str(trade['side']).lower(),
                                size=trade_size,
                                price=Decimal(str(trade['price'])),
                                strategy="copy_whale",
                                fees=fees,
                                gas=gas,
                                whale_source=whale_addr or "",
                                opportunity_id=opportunity_id,
                                market_title=market_title,
                            )
                            logger.info(
                                f"  Paper trade executed: {result.trade_id}, "
                                f"new balance: {virtual_bankroll.balance}"
                            )
                        except Exception as e:
                            logger.warning(f"  Error executing paper trade: {e}")
                
                else:
                    logger.info("No pending paper trades found")
                
                # Log bankroll stats
                stats = virtual_bankroll.get_stats()
                logger.info(
                    f"Status: Balance=${stats.current_balance:.2f} | "
                    f"Trades: {stats.total_trades} | "
                    f"Win Rate: {stats.win_rate*100:.1f}%"
                )
            
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        notification_worker.stop()
        notification_task.cancel()
        
    # Print final stats
    stats = virtual_bankroll.get_stats()
    logger.info(f"Final balance: ${stats.current_balance:.2f}")
    logger.info(f"Total trades: {stats.total_trades}")
    logger.info(f"Win rate: {stats.win_rate*100:.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
