# -*- coding: utf-8 -*-
"""Main entry point for trading bot."""

import asyncio
import argparse

from src.monitoring import get_logger

logger = get_logger(__name__)


async def main():
    """Main trading loop."""
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--bankroll", type=float, default=100.0)
    args = parser.parse_args()

    logger.info(f"Starting bot in {args.mode} mode with ${args.bankroll} bankroll")

    # TODO: Initialize components
    # - Data ingestion
    # - Strategy engine
    # - Execution orchestrator
    # - Risk management

    try:
        while True:
            # Main trading loop
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
