# -*- coding: utf-8 -*-
"""Realistic Polymarket Paper Trading Simulation - Whale Copy Strategy."""

import asyncio
import random
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional


class RealisticMarket:
    def __init__(
        self,
        market_id: str,
        question: str,
        category: str,
        base_price: float,
        volatility: float = 0.05,
    ):
        self.market_id = market_id
        self.question = question
        self.category = category
        self.base_price = base_price
        self.volatility = volatility
        self.current_price = Decimal(str(base_price))

    def update(self) -> Decimal:
        change = random.gauss(0, self.volatility)
        new_price = float(self.current_price) + change
        new_price = max(0.05, min(0.95, new_price))
        self.current_price = Decimal(str(round(new_price, 4)))
        return self.current_price


class WhaleTrackRecord:
    def __init__(self, address: str, win_rate: float, avg_return: float):
        self.address = address
        self.win_rate = win_rate
        self.avg_return = avg_return


class RealisticPolymarketPaperTrader:
    MARKETS = [
        (
            "US-ELECTION-2026",
            "Will Republican win 2026 Midterms?",
            "Politics",
            0.52,
            0.03,
        ),
        (
            "FED-RATE-MAR-2026",
            "Will Fed cut rates in March 2026?",
            "Economy",
            0.45,
            0.04,
        ),
        (
            "BTC-PRICE-JUN-2026",
            "Will BTC hit $150K by June 2026?",
            "Crypto",
            0.38,
            0.05,
        ),
        ("ETH-PRICE-2026", "Will ETH hit $5K by end of 2026?", "Crypto", 0.42, 0.05),
        (
            "INFLATION-CPI-2026",
            "Will US inflation stay below 3%?",
            "Economy",
            0.58,
            0.03,
        ),
        ("GDP-GROWTH-2026", "Will US GDP grow >2% in 2026?", "Economy", 0.65, 0.03),
        (
            "AI-REGULATION-2026",
            "Will major AI regulation pass in 2026?",
            "Tech",
            0.40,
            0.04,
        ),
        (
            "CHINA-TRADE-2026",
            "Will US-China trade deal happen?",
            "Politics",
            0.35,
            0.04,
        ),
        ("SP500-2026", "Will S&P 500 hit 6000 in 2026?", "Markets", 0.48, 0.04),
        ("UK-ELECTION-2026", "Will Labour win UK election?", "Politics", 0.55, 0.04),
        ("MARS-COLONY-2026", "Will SpaceX land humans on Mars?", "Science", 0.15, 0.08),
        ("NVIDIA-EARNINGS-2026", "Will NVIDIA beat earnings Q1?", "Tech", 0.55, 0.03),
        ("RUSSIA-UKRAINE-2026", "Will Russia-Ukraine war end?", "Politics", 0.28, 0.05),
        (
            "COVID-END-2026",
            "Will WHO declare COVID emergency over?",
            "Health",
            0.70,
            0.03,
        ),
    ]

    WHALE_TRACK_RECORDS = [
        ("0x742d...3Eb3", 0.72, 0.15),
        ("0x8Cda...7E7", 0.68, 0.12),
        ("0x3A5d...5d3", 0.75, 0.18),
        ("0x1a2B...678", 0.65, 0.10),
        ("0x9abc...789", 0.70, 0.14),
    ]

    def __init__(
        self,
        initial_balance: Decimal = Decimal("100.00"),
        target_balance: Decimal = Decimal("125.00"),
        kelly_fraction: Decimal = Decimal("0.25"),
        seed: int = 42,
    ):
        self.initial_balance = initial_balance
        self.target_balance = target_balance
        self.kelly_fraction = kelly_fraction
        self.rng = random.Random(seed)

        self.balance = initial_balance
        self.open_positions: Dict[str, Dict] = {}

        self.whales = [
            WhaleTrackRecord(addr, wr, ret)
            for addr, wr, ret in self.WHALE_TRACK_RECORDS
        ]

        self.markets = {}
        for market_id, question, category, price, vol in self.MARKETS:
            self.markets[market_id] = RealisticMarket(
                market_id, question, category, price, vol
            )

        self._total_wins = 0
        self._total_losses = 0
        self._consecutive_losses = 0

    def calculate_position_size(
        self, whale: WhaleTrackRecord, market_id: str
    ) -> Decimal:
        b = Decimal(str(whale.avg_return + 1))
        p = Decimal(str(whale.win_rate))
        q = Decimal("1") - p

        kelly = (b * p - q) / b
        safe_kelly = max(kelly * self.kelly_fraction, Decimal("0.02"))

        max_size = self.balance * Decimal("0.05")
        position = self.balance * safe_kelly

        return min(position, max_size)

    def copy_whale_trade(
        self, whale: WhaleTrackRecord, market_id: str, side: str
    ) -> Optional[Dict]:
        market = self.markets.get(market_id)
        if not market:
            return None

        position_size = self.calculate_position_size(whale, market_id)
        if position_size < Decimal("1"):
            return None

        entry_price = market.current_price
        fees = position_size * Decimal("0.01") + Decimal("0.25")

        if entry_price * position_size + fees > self.balance:
            return None

        self.balance -= fees
        self.open_positions[market_id] = {
            "whale": whale.address,
            "side": side,
            "size": position_size,
            "entry_price": entry_price,
            "fees": fees,
            "market_question": market.question,
        }

        return {
            "market_id": market_id,
            "whale": whale.address[:10],
            "side": side,
            "size": position_size,
            "entry_price": entry_price,
            "fees": fees,
            "new_balance": self.balance,
        }

    def close_position(
        self, market_id: str, reason: str = "whale_exit"
    ) -> Optional[Dict]:
        if market_id not in self.open_positions:
            return None

        pos = self.open_positions[market_id]
        market = self.markets.get(market_id)
        if not market:
            return None

        exit_price = market.current_price
        exit_fees = pos["size"] * Decimal("0.01") + Decimal("0.25")

        if pos["side"] == "buy":
            pnl = (exit_price - pos["entry_price"]) * pos["size"]
        else:
            pnl = (pos["entry_price"] - exit_price) * pos["size"]

        net_pnl = pnl - pos["fees"] - exit_fees
        self.balance += pos["size"] * exit_price - exit_fees

        if net_pnl > 0:
            self._total_wins += 1
            self._consecutive_losses = 0
        else:
            self._total_losses += 1
            self._consecutive_losses += 1

        del self.open_positions[market_id]

        return {
            "market_id": market_id,
            "side": pos["side"],
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "pnl": net_pnl,
            "reason": reason,
            "new_balance": self.balance,
        }

    def get_stats(self) -> Dict:
        total = self._total_wins + self._total_losses
        win_rate = self._total_wins / total if total > 0 else 0

        return {
            "balance": self.balance,
            "total_trades": total,
            "wins": self._total_wins,
            "losses": self._total_losses,
            "win_rate": win_rate,
            "consecutive_losses": self._consecutive_losses,
            "open_positions": len(self.open_positions),
            "roi": ((self.balance - self.initial_balance) / self.initial_balance) * 100,
        }

    def check_criteria(self) -> Dict:
        stats = self.get_stats()

        return {
            "balance_above_target": self.balance >= self.target_balance,
            "win_rate_above_min": stats["win_rate"] >= 0.60,
            "consecutive_losses_acceptable": self._consecutive_losses <= 3,
            "all_criteria_met": (
                self.balance >= self.target_balance
                and stats["win_rate"] >= 0.60
                and self._consecutive_losses <= 3
            ),
        }

    async def run_session(
        self, num_days: int = 7, trades_per_day: int = 15, close_frequency: int = 4
    ):
        total_trades = num_days * trades_per_day

        print("=" * 70)
        print("REALISTIC POLYMARKET PAPER TRADING - WHALE COPY STRATEGY")
        print("=" * 70)
        print(f"Session: {num_days} days ({total_trades} trades)")
        print(f"Initial Balance: ${float(self.initial_balance):.2f}")
        print(f"Target: ${float(self.target_balance):.2f} (25% ROI)")
        print(f"Kelly Fraction: {float(self.kelly_fraction) * 100:.0f}%")
        print()

        print("Markets Tracked:")
        for mid, m in list(self.markets.items())[:5]:
            print(f"  - {m.question[:45]}... @ ${float(m.current_price):.2f}")
        print(f"  ... ({len(self.markets)} total markets)")
        print()

        whale_names = [w.address[:10] for w in self.whales]
        print(f"Whales Followed: {', '.join(whale_names)}")
        print()

        for day in range(num_days):
            for market in self.markets.values():
                market.update()

            for trade_num in range(trades_per_day):
                whale = self.whales[trade_num % len(self.whales)]
                market = list(self.markets.values())[trade_num % len(self.markets)]
                side = "BUY" if trade_num % 4 != 3 else "SELL"

                if market.market_id not in self.open_positions:
                    result = self.copy_whale_trade(whale, market.market_id, side)

                    if result:
                        print(
                            f"Day {day + 1} [{trade_num + 1}]: COPY {side} {market.market_id[:15]}... "
                            f"${float(result['size']):.2f} @ ${float(result['entry_price']):.2f}"
                        )

                elif trade_num % close_frequency == 0:
                    close_result = self.close_position(market.market_id)
                    if close_result:
                        pnl = close_result["pnl"]
                        pnl_str = (
                            f"+${float(pnl):.2f}"
                            if pnl > 0
                            else f"-${abs(float(pnl)):.2f}"
                        )
                        print(
                            f"Day {day + 1} [{trade_num + 1}]: CLOSE {market.market_id[:15]}... "
                            f"{pnl_str} | Balance: ${float(self.balance):.2f}"
                        )

            stats = self.get_stats()
            print(
                f"Day {day + 1} Summary: Balance=${float(self.balance):.2f}, "
                f"WinRate={stats['win_rate'] * 100:.1f}%, ROI={stats['roi']:.1f}%"
            )
            print()

        for market_id in list(self.open_positions.keys()):
            self.close_position(market_id, reason="final_close")

        stats = self.get_stats()
        criteria = self.check_criteria()

        print("=" * 70)
        print("FINAL RESULTS")
        print("=" * 70)
        print(f"Duration: {num_days} simulated days")
        print()
        print(f"Initial Balance:    ${float(self.initial_balance):>10.2f}")
        print(f"Final Balance:      ${float(stats['balance']):>10.2f}")
        print(
            f"Total PnL:          ${float(stats['balance'] - self.initial_balance):>10.2f}"
        )
        print(f"ROI:                {stats['roi']:>10.1f}%")
        print()
        print(f"Total Closed:       {stats['total_trades']:>10d}")
        print(f"Winning Trades:     {stats['wins']:>10d}")
        print(f"Losing Trades:       {stats['losses']:>10d}")
        print(f"Win Rate:           {stats['win_rate'] * 100:>10.1f}%")
        print(f"Open Positions:     {stats['open_positions']:>10d}")
        print(f"Consecutive Losses: {stats['consecutive_losses']:>10d}")
        print()
        print("-" * 70)
        print("SUCCESS CRITERIA:")
        print("-" * 70)
        print(
            f"  [ {'X' if criteria['balance_above_target'] else ' '} ] Balance >= $125: ${float(stats['balance']):.2f}"
        )
        print(
            f"  [ {'X' if criteria['win_rate_above_min'] else ' '} ] Win Rate >= 60%: {stats['win_rate'] * 100:.1f}%"
        )
        print(
            f"  [ {'X' if criteria['consecutive_losses_acceptable'] else ' '} ] Consec Losses <= 3: {stats['consecutive_losses']}"
        )
        print()
        print("=" * 70)
        if criteria["all_criteria_met"]:
            print("ALL CRITERIA MET - READY FOR LIVE TRADING!")
        else:
            print("CRITERIA NOT MET - CONTINUE PAPER TRADING")
        print("=" * 70)

        return stats, criteria


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Realistic Polymarket Paper Trading")
    parser.add_argument("--days", type=int, default=7, help="Number of days")
    parser.add_argument("--trades-per-day", type=int, default=15, help="Trades per day")
    args = parser.parse_args()

    trader = RealisticPolymarketPaperTrader(
        initial_balance=Decimal("100.00"),
        target_balance=Decimal("125.00"),
        kelly_fraction=Decimal("0.25"),
        seed=42,
    )
    await trader.run_session(num_days=args.days, trades_per_day=args.trades_per_day)


if __name__ == "__main__":
    asyncio.run(main())
