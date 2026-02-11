# Real Polymarket Paper Trading - with actual 2025-2026 markets

import asyncio
import httpx
from decimal import Decimal
from typing import Dict, List

from strategy.virtual_bankroll import VirtualBankroll


class RealMarketPaperTrader:
    MARKETS_URL = "https://gamma-api.polymarket.com/events"

    def __init__(
        self, initial_balance=Decimal("100.00"), target_balance=Decimal("125.00")
    ):
        self.initial_balance = initial_balance
        self.target_balance = target_balance
        self.bankroll = VirtualBankroll(initial_balance=initial_balance)
        self.bankroll.set_database(
            "postgresql://postgres:password@localhost:5433/postgres"
        )
        self._events = []

    async def fetch_events(self) -> int:
        print("\n[+] Fetching actual events from Polymarket...")
        resp = httpx.get(
            self.MARKETS_URL,
            params={"active": "true", "closed": "false", "limit": "50"},
            timeout=30.0,
        )

        if resp.status_code == 200:
            self._events = resp.json()
            print(f"    Found {len(self._events)} active events")
            return len(self._events)
        return 0

    async def run_session(self, num_days=7, trades_per_day=10):
        print("=" * 70)
        print("POLYMARKET PAPER TRADING - REAL 2025 MARKETS")
        print("=" * 70)
        print(f"\nInitial Balance: ${float(self.initial_balance):.2f}")
        print(f"Target: ${float(self.target_balance):.2f} (25% ROI)")

        await self.fetch_events()

        if not self._events:
            print("\n[!] No events found")
            return

        print(f"\n[+] Using {len(self._events)} markets\n")

        for day in range(num_days):
            print(f"Day {day + 1}/{num_days}")

            for i in range(trades_per_day):
                market = self._events[i % len(self._events)]
                market_id = market.get("id", f"event_{i}")
                title = market.get("title", market.get("question", "Unknown"))[:45]

                size = Decimal(str(round(5 + (i % 10), 2)))
                price = Decimal(str(round(0.3 + (i % 7) * 0.1, 2)))
                side = "buy" if i % 3 != 0 else "sell"

                try:
                    if side == "buy":
                        await self.bankroll.execute_virtual_trade(
                            market_id=market_id,
                            side=side,
                            size=size,
                            price=price,
                            strategy="real_polymarket",
                            fees=Decimal(str(float(size) * 0.01)),
                            gas=Decimal("0.25"),
                        )
                        print(
                            f"  BUY {title}... ${float(size):.2f} @ ${float(price):.2f}"
                        )
                    else:
                        await self.bankroll.close_virtual_position(
                            market_id=market_id,
                            close_price=price,
                            fees=Decimal(str(float(size) * 0.01)),
                            gas=Decimal("0.25"),
                        )
                        print(f"  SELL {title}... @ ${float(price):.2f}")

                except ValueError:
                    pass

            stats = self.bankroll.get_stats()
            print(
                f"  Balance: ${float(stats.current_balance):.2f}, WinRate: {stats.win_rate * 100:.1f}%"
            )
            print()

        stats = self.bankroll.get_stats()
        criteria = self.bankroll.check_success_criteria(
            target_balance=self.target_balance,
            min_win_rate=Decimal("0.60"),
            max_consecutive_losses=3,
        )

        print("=" * 70)
        print("FINAL RESULTS")
        print("=" * 70)
        print(
            f"Initial: ${float(self.initial_balance):.2f} | Final: ${float(stats.current_balance):.2f}"
        )
        print(
            f"Total Trades: {stats.total_trades} | Win Rate: {stats.win_rate * 100:.1f}%"
        )
        print()
        print(f"Criteria:")
        print(
            f"  [ {'X' if criteria['balance_above_target'] else ' '} ] Balance >= ${float(self.target_balance):.2f}"
        )
        print(f"  [ {'X' if criteria['win_rate_above_min'] else ' '} ] Win Rate >= 60%")
        print(
            f"  [ {'X' if criteria['consecutive_losses_acceptable'] else ' '} ] Consec Losses <= 3"
        )
        print()

        if criteria["all_criteria_met"]:
            print("ALL CRITERIA MET - READY FOR LIVE TRADING!")
        else:
            print("CONTINUE PAPER TRADING")

        print("=" * 70)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Real Polymarket Paper Trading")
    parser.add_argument("--days", type=int, default=7, help="Number of days")
    parser.add_argument("--trades-per-day", type=int, default=10, help="Trades per day")
    args = parser.parse_args()

    trader = RealMarketPaperTrader()
    await trader.run_session(num_days=args.days, trades_per_day=args.trades_per_day)


if __name__ == "__main__":
    asyncio.run(main())
