# -*- coding: utf-8 -*-
"""Main entry point for trading bot with whale copy trading."""

import asyncio
import argparse
import os
from decimal import Decimal

from src.monitoring import get_logger
from src.research.whale_tracker import WhaleTracker
from src.strategy.virtual_bankroll import VirtualBankroll

logger = get_logger(__name__)


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
    check_interval = 300  # Check every 5 minutes
    
    try:
        while True:
            loop_count += 1
            
            # Every check_interval iterations, fetch new trades from whales
            if loop_count % check_interval == 0:
                logger.info(f"Checking whale trades (loop {loop_count})...")
                
                for whale_addr in whale_addresses[:5]:  # Check top 5 whales
                    try:
                        # Fetch recent trades for this whale
                        trades = await whale_tracker.fetch_whale_trades(
                            whale_addr, limit=20
                        )
                        
                        if trades:
                            logger.info(
                                f"Whale {whale_addr[:8]}... has {len(trades)} recent trades"
                            )
                            
                            # Process each trade - in paper mode, just log it
                            # In live mode, would execute real trades
                            for trade in trades[:3]:  # Process up to 3 trades
                                logger.info(
                                    f"  Trade: {trade.side} ${trade.size_usd:.0f} "
                                    f"at {trade.price} on {trade.market_id[:16]}..."
                                )
                                
                    except Exception as e:
                        logger.warning(f"Error fetching trades for {whale_addr[:8]}: {e}")
                
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
        
    # Print final stats
    stats = virtual_bankroll.get_stats()
    logger.info(f"Final balance: ${stats.current_balance:.2f}")
    logger.info(f"Total trades: {stats.total_trades}")
    logger.info(f"Win rate: {stats.win_rate*100:.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
