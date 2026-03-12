# -*- coding: utf-8 -*-
"""Paper Settlement Runtime Service.

Runs the PaperPositionSettlementEngine in a loop to automatically
settle paper positions when markets resolve on Polymarket.

Usage:
    python src/runtime/paper_settlement_service.py

Environment:
    DATABASE_URL: PostgreSQL connection URL
    SETTLEMENT_INTERVAL: Seconds between settlement checks (default: 600)
"""

import asyncio
import os
import signal
import sys

import structlog

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.paper_position_settlement import PaperPositionSettlementEngine

logger = structlog.get_logger(__name__)


def get_database_url() -> str:
    """Get database URL from environment."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5433/polymarket"
    )


def get_interval() -> int:
    """Get settlement interval from environment."""
    return int(os.environ.get("SETTLEMENT_INTERVAL", "600"))


class PaperSettlementService:
    """Runtime service for paper position settlement.
    
    Runs the settlement engine in a loop, checking for market
    resolutions and settling paper positions accordingly.
    """
    
    def __init__(self, database_url: str, interval_seconds: int = 600) -> None:
        """Initialize the service.
        
        Args:
            database_url: PostgreSQL connection URL
            interval_seconds: Seconds between settlement cycles
        """
        self.database_url = database_url
        self.interval_seconds = interval_seconds
        self.engine = PaperPositionSettlementEngine(database_url)
        self.running = False
        
        logger.info(
            "paper_settlement_service_initialized",
            database_url="postgresql://postgres:***@***/***",
            interval_seconds=interval_seconds,
        )
    
    async def run_cycle(self) -> None:
        """Run a single settlement cycle."""
        try:
            logger.info("starting_settlement_cycle")
            result = await self.engine.settle_resolved_paper_positions()
            logger.info(
                "settlement_cycle_complete",
                checked=result.get("checked", 0),
                settled=result.get("settled", 0),
                resolved=result.get("resolved", 0),
                failed=result.get("failed", 0),
                markets_not_resolved=result.get("markets_not_resolved", 0),
            )
        except Exception as e:
            logger.error("settlement_cycle_error", error=str(e))
    
    async def run(self) -> None:
        """Run the settlement service in a loop."""
        self.running = True
        
        logger.info(
            "paper_settlement_service_started",
            interval_seconds=self.interval_seconds,
        )
        
        while self.running:
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error("settlement_loop_error", error=str(e))
            
            # Sleep before next cycle
            await asyncio.sleep(self.interval_seconds)
    
    def stop(self) -> None:
        """Stop the service gracefully."""
        logger.info("paper_settlement_service_stopping")
        self.running = False


async def main() -> None:
    """Main entry point."""
    database_url = get_database_url()
    interval_seconds = get_interval()
    
    logger.info(
        "paper_settlement_runtime_starting",
        interval_seconds=interval_seconds,
    )
    
    service = PaperSettlementService(database_url, interval_seconds)
    
    # Setup graceful shutdown
    def signal_handler(signum, frame):
        logger.info("received_shutdown_signal", signal=signum)
        service.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await service.run()
    finally:
        await service.engine.close()
        logger.info("paper_settlement_service_stopped")


if __name__ == "__main__":
    # Configure logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    asyncio.run(main())
