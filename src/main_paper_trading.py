# -*- coding: utf-8 -*-
"""Paper Trading Runner for 7-Day Validation.

Runs paper trading simulation for 7 days (168 hours minimum)
before allowing live trading. Tracks virtual bankroll and
validates success criteria.

Usage:
    python src/main_paper_trading.py --mode paper --duration 7d
    python src/main_paper_trading.py --mode paper --target-balance 125.0

Success Criteria for Live Trading:
    - Virtual balance > $125 (25% ROI)
    - Win rate > 60%
    - No consecutive losses > 3
    - Minimum 7 days (168 hours) paper trading
"""

import asyncio
import logging
import signal
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import structlog

from config.settings import settings
from strategy.virtual_bankroll import VirtualBankroll, BankrollStats
from execution.copy_trading_engine import CopyTradingEngine

logger = structlog.get_logger(__name__)

logging.basicConfig(level=logging.INFO)


class PaperTradingRunner:
    """Paper Trading Runner for 7-Day Validation.

    Manages paper trading simulation, tracks virtual bankroll,
    and validates success criteria for live trading.

    Attributes:
        initial_balance: Starting virtual balance ($100 default)
        target_balance: Target balance for success ($125 default)
        min_win_rate: Minimum win rate (60% default)
        max_consecutive_losses: Maximum consecutive losses allowed (3 default)
        min_duration_hours: Minimum paper trading duration (168 hours default)
    """

    DEFAULT_INITIAL_BALANCE = Decimal("100.00")
    DEFAULT_TARGET_BALANCE = Decimal("125.00")
    DEFAULT_MIN_WIN_RATE = Decimal("0.60")
    DEFAULT_MAX_CONSECUTIVE_LOSSES = 3
    DEFAULT_MIN_DURATION_HOURS = 168

    def __init__(
        self,
        initial_balance: Decimal = DEFAULT_INITIAL_BALANCE,
        target_balance: Decimal = DEFAULT_TARGET_BALANCE,
        min_win_rate: Decimal = DEFAULT_MIN_WIN_RATE,
        max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
        min_duration_hours: int = DEFAULT_MIN_DURATION_HOURS,
        database_url: Optional[str] = None,
    ) -> None:
        """Initialize Paper Trading Runner.

        Args:
            initial_balance: Starting virtual balance
            target_balance: Target balance for success
            min_win_rate: Minimum win rate percentage
            max_consecutive_losses: Maximum consecutive losses allowed
            min_duration_hours: Minimum hours of paper trading
            database_url: PostgreSQL connection URL
        """
        self.initial_balance = initial_balance
        self.target_balance = target_balance
        self.min_win_rate = min_win_rate
        self.max_consecutive_losses = max_consecutive_losses
        self.min_duration_hours = min_duration_hours

        self.virtual_bankroll = VirtualBankroll(
            initial_balance=initial_balance,
            database_url=database_url or settings.database_url,
        )

        self.is_running = False
        self.start_time: Optional[datetime] = None
        self.last_stats_time: Optional[datetime] = None
        self.copy_trading_engine: Optional[CopyTradingEngine] = None

        self.daily_stats: list[dict] = []

        logger.info(
            "paper_trading_runner_initialized",
            initial_balance=str(initial_balance),
            target_balance=str(target_balance),
            min_win_rate=str(min_win_rate),
            min_duration_hours=min_duration_hours,
        )

    def set_copy_trading_engine(self, engine: CopyTradingEngine) -> None:
        """Set the Copy Trading Engine for paper mode.

        Args:
            engine: CopyTradingEngine instance
        """
        self.copy_trading_engine = engine
        logger.info("copy_trading_engine_configured_for_paper")

    async def start(self, duration_hours: Optional[int] = None) -> dict:
        """Start paper trading simulation.

        Args:
            duration_hours: Optional duration override in hours

        Returns:
            Dict with final results and statistics

        Raises:
            ValueError: If duration_hours is not positive
        """
        duration = duration_hours or self.min_duration_hours
        if duration <= 0:
            raise ValueError("Duration must be positive")

        self.is_running = True
        self.start_time = datetime.now()
        end_time = self.start_time + timedelta(hours=duration)

        logger.info(
            "paper_trading_started",
            start_time=self.start_time.isoformat(),
            end_time=end_time.isoformat(),
            duration_hours=duration,
        )

        loop = asyncio.get_event_loop()
        stop_event = asyncio.Event()

        def signal_handler() -> None:
            logger.info("paper_trading_received_shutdown_signal")
            stop_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, signal_handler)
            except NotImplementedError:
                # Windows compatibility: signal handlers are not supported on some loops
                pass

        stats_task = asyncio.create_task(self._stats_printer(stop_event))
        criteria_task = asyncio.create_task(self._criteria_monitor(stop_event))

        await stop_event.wait()

        self.is_running = False

        stats_task.cancel()
        criteria_task.cancel()

        return await self.get_final_results()

    async def _stats_printer(self, stop_event: asyncio.Event) -> None:
        """Print statistics every 24 hours."""
        while not stop_event.is_set():
            await asyncio.sleep(3600)
            if not self.is_running:
                break

            stats = self.virtual_bankroll.get_stats()
            elapsed = (
                datetime.now() - self.start_time if self.start_time else timedelta(0)
            )

            logger.info(
                "paper_trading_daily_stats",
                elapsed_hours=elapsed.total_seconds() / 3600,
                balance=str(stats.current_balance),
                total_trades=stats.total_trades,
                open_positions=stats.open_positions,
                win_rate=str(stats.win_rate * 100),
                total_pnl=str(stats.total_pnl),
                roi_percent=str(self.virtual_bankroll.get_roi_percent()),
                consecutive_losses=stats.consecutive_losses,
            )

    async def _criteria_monitor(self, stop_event: asyncio.Event) -> None:
        """Monitor and report on success criteria."""
        while not stop_event.is_set():
            await asyncio.sleep(300)

            criteria = self.virtual_bankroll.check_success_criteria(
                target_balance=self.target_balance,
                min_win_rate=self.min_win_rate,
                max_consecutive_losses=self.max_consecutive_losses,
            )

            elapsed = (
                datetime.now() - self.start_time if self.start_time else timedelta(0)
            )
            hours_elapsed = elapsed.total_seconds() / 3600

            logger.info(
                "paper_trading_criteria_check",
                hours_elapsed=round(hours_elapsed, 1),
                balance_met=criteria["balance_above_target"],
                win_rate_met=criteria["win_rate_above_min"],
                losses_met=criteria["consecutive_losses_acceptable"],
                all_met=criteria["all_criteria_met"],
            )

    async def get_final_results(self) -> dict:
        """Get final paper trading results.

        Returns:
            Dict with complete results and recommendation
        """
        stats = self.virtual_bankroll.get_stats()
        elapsed = datetime.now() - self.start_time if self.start_time else timedelta(0)

        criteria = self.virtual_bankroll.check_success_criteria(
            target_balance=self.target_balance,
            min_win_rate=self.min_win_rate,
            max_consecutive_losses=self.max_consecutive_losses,
        )

        min_duration_met = elapsed.total_seconds() >= (self.min_duration_hours * 3600)

        all_criteria_met = (
            criteria["balance_above_target"]
            and criteria["win_rate_above_min"]
            and criteria["consecutive_losses_acceptable"]
            and min_duration_met
        )

        results = {
            "status": "SUCCESS" if all_criteria_met else "IN_PROGRESS",
            "duration_hours": elapsed.total_seconds() / 3600,
            "min_duration_hours": self.min_duration_hours,
            "duration_met": min_duration_met,
            "virtual_bankroll": {
                "initial_balance": str(self.initial_balance),
                "final_balance": str(stats.current_balance),
                "roi_percent": str(self.virtual_bankroll.get_roi_percent()),
                "total_pnl": str(stats.total_pnl),
            },
            "trading_stats": {
                "total_trades": stats.total_trades,
                "winning_trades": stats.winning_trades,
                "losing_trades": stats.losing_trades,
                "win_rate": str(stats.win_rate * 100),
                "open_positions": stats.open_positions,
                "consecutive_losses": stats.consecutive_losses,
                "max_consecutive_losses": stats.max_consecutive_losses,
            },
            "success_criteria": {
                "target_balance": str(self.target_balance),
                "balance_above_target": criteria["balance_above_target"],
                "min_win_rate": str(self.min_win_rate * 100),
                "win_rate_above_min": criteria["win_rate_above_min"],
                "max_consecutive_losses": self.max_consecutive_losses,
                "consecutive_losses_acceptable": criteria[
                    "consecutive_losses_acceptable"
                ],
                "all_criteria_met": all_criteria_met,
            },
            "recommendation": (
                "READY FOR LIVE TRADING"
                if all_criteria_met
                else "CONTINUE PAPER TRADING"
            ),
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(
            "paper_trading_results",
            status=results["status"],
            final_balance=str(stats.current_balance),
            roi_percent=str(self.virtual_bankroll.get_roi_percent()),
            win_rate=str(stats.win_rate * 100),
            recommendation=results["recommendation"],
        )

        return results

    async def log_virtual_trade(
        self,
        market_id: str,
        side: str,
        size: Decimal,
        price: Decimal,
        strategy: str,
        fees: Decimal = Decimal("0.00"),
        gas: Decimal = Decimal("0.00"),
    ) -> None:
        """Log a virtual trade (for CopyTradingEngine integration).

        Args:
            market_id: Market identifier
            side: Trade side ("buy" or "sell")
            size: Position size
            price: Execution price
            strategy: Trading strategy
            fees: Trading fees
            gas: Gas costs
        """
        await self.virtual_bankroll.execute_virtual_trade(
            market_id=market_id,
            side=side,
            size=size,
            price=price,
            strategy=strategy,
            fees=fees,
            gas=gas,
        )

    def get_stats(self) -> BankrollStats:
        """Get current bankroll statistics.

        Returns:
            BankrollStats with all metrics
        """
        return self.virtual_bankroll.get_stats()


async def run_demo_paper_trading():
    """Run a demonstration of paper trading with mock signals."""
    print("=" * 60)
    print("Paper Trading Demo - Virtual Bankroll v0.4.0")
    print("=" * 60)

    runner = PaperTradingRunner(
        initial_balance=Decimal("100.00"),
        target_balance=Decimal("125.00"),
        min_win_rate=Decimal("0.60"),
        max_consecutive_losses=3,
        min_duration_hours=168,
    )

    bankroll = runner.virtual_bankroll

    print(f"\nInitial Balance: ${bankroll.balance:.2f}")
    print("Target Balance: $125.00 (25% ROI)")
    print("Minimum Win Rate: 60%")
    print("Minimum Duration: 168 hours (7 days)")
    print()

    mock_trades = [
        {
            "market_id": "0xmarket1",
            "side": "buy",
            "size": Decimal("10.0"),
            "price": Decimal("0.50"),
            "fees": Decimal("0.10"),
            "strategy": "copy",
        },
        {
            "market_id": "0xmarket2",
            "side": "buy",
            "size": Decimal("15.0"),
            "price": Decimal("0.60"),
            "fees": Decimal("0.18"),
            "strategy": "copy",
        },
        {
            "market_id": "0xmarket3",
            "side": "buy",
            "size": Decimal("8.0"),
            "price": Decimal("0.45"),
            "fees": Decimal("0.08"),
            "strategy": "copy",
        },
    ]

    print("Executing mock trades...")
    for trade in mock_trades:
        result = await bankroll.execute_virtual_trade(
            market_id=trade["market_id"],
            side=trade["side"],
            size=trade["size"],
            price=trade["price"],
            strategy=trade["strategy"],
            fees=trade["fees"],
        )
        print(
            f"  {trade['side'].upper()} {trade['size']} @ ${trade['price']:.2f} - Balance: ${bankroll.balance:.2f}"
        )

    print("\nClosing some positions...")
    close_trades = [
        {
            "market_id": "0xmarket1",
            "close_price": Decimal("0.55"),
            "fees": Decimal("0.10"),
        },
        {
            "market_id": "0xmarket2",
            "close_price": Decimal("0.58"),
            "fees": Decimal("0.15"),
        },
    ]

    for close in close_trades:
        result = await bankroll.close_virtual_position(
            market_id=close["market_id"],
            close_price=close["close_price"],
            fees=close["fees"],
        )
        print(
            f"  CLOSE {close['market_id']} @ ${close['close_price']:.2f} - PnL: ${result.net_pnl:.2f} - Balance: ${bankroll.balance:.2f}"
        )

    stats = bankroll.get_stats()
    criteria = bankroll.check_success_criteria()

    print("\n" + "=" * 60)
    print("FINAL STATISTICS")
    print("=" * 60)
    print(f"Current Balance: ${stats.current_balance:.2f}")
    print(f"Total Trades: {stats.total_trades}")
    print(f"Win Rate: {stats.win_rate * 100:.1f}%")
    print(f"Total PnL: ${stats.total_pnl:.2f}")
    print(f"Consecutive Losses: {stats.consecutive_losses}")
    print()
    print("Success Criteria:")
    print(f"  Balance > $125: {criteria['balance_above_target']}")
    print(f"  Win Rate > 60%: {criteria['win_rate_above_min']}")
    print(f"  Consecutive Losses ≤ 3: {criteria['consecutive_losses_acceptable']}")
    print(f"  ALL CRITERIA MET: {criteria['all_criteria_met']}")

    return runner


async def main():
    """Main entry point for paper trading runner."""
    import argparse

    parser = argparse.ArgumentParser(description="Paper Trading Runner for v0.4.0")
    parser.add_argument(
        "--mode",
        choices=["demo", "paper"],
        default="demo",
        help="Mode: demo (quick test) or paper (full 7-day simulation)",
    )
    parser.add_argument(
        "--duration",
        type=str,
        default="7d",
        help="Duration (e.g., '7d', '24h', '168h')",
    )
    parser.add_argument(
        "--initial-balance", type=float, default=100.0, help="Initial virtual balance"
    )
    parser.add_argument(
        "--target-balance",
        type=float,
        default=125.0,
        help="Target virtual balance for success",
    )

    args = parser.parse_args()

    duration_hours = 168
    if args.duration.endswith("d"):
        duration_hours = int(args.duration[:-1]) * 24
    elif args.duration.endswith("h"):
        duration_hours = int(args.duration[:-1])

    if args.mode == "demo":
        await run_demo_paper_trading()
    else:
        runner = PaperTradingRunner(
            initial_balance=Decimal(str(args.initial_balance)),
            target_balance=Decimal(str(args.target_balance)),
        )
        results = await runner.start(duration_hours=duration_hours)
        print("\n" + "=" * 60)
        print("PAPER TRADING COMPLETE")
        print("=" * 60)
        print(f"Status: {results['status']}")
        print(f"Final Balance: ${results['virtual_bankroll']['final_balance']}")
        print(f"ROI: {results['virtual_bankroll']['roi_percent']}%")
        print(f"Win Rate: {results['trading_stats']['win_rate']}%")
        print(f"\nRecommendation: {results['recommendation']}")


if __name__ == "__main__":
    asyncio.run(main())
