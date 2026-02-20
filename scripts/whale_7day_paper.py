import asyncio
import asyncpg
import os
from decimal import Decimal
import random
from datetime import datetime, timedelta


async def main():
    db_url = os.getenv(
        "DATABASE_URL", "postgresql://postgres:password@localhost:5433/postgres"
    )
    conn = await asyncpg.connect(db_url)

    # Get quality whales
    whales = await conn.fetch(
        "SELECT * FROM whales WHERE win_rate >= 0.60 ORDER BY win_rate DESC"
    )
    print(f"Quality whales: {len(whales)}")

    # Get whale trades
    trades = await conn.fetch("""
        SELECT wt.*, w.win_rate, w.risk_score
        FROM whale_trades wt
        JOIN whales w ON wt.whale_id = w.id
        ORDER BY wt.traded_at DESC
        LIMIT 500
    """)
    print(f"Total whale trades: {len(trades)}")

    # Group by whale
    whale_trades = {}
    for t in trades:
        wid = t["whale_id"]
        if wid not in whale_trades:
            whale_trades[wid] = {"trades": [], "wr": float(t["win_rate"])}
        whale_trades[wid]["trades"].append(t)

    # Paper trading: 7 days, 5 trades per day = 35 trades
    print("\n=== 7-Day Paper Trading Simulation ===")
    print("Using real whale trades with win rate simulation")
    print("Initial balance: $100")
    print("Position: 15% of bankroll")
    print("Duration: 7 days (35 trades)")
    print()

    results = []

    for sim in range(30):
        balance = Decimal("100.00")
        wins = 0
        losses = 0
        trade_log = []

        # Use whale trades as signals
        all_signals = []
        for wid, data in whale_trades.items():
            wr = data["wr"]
            for t in data["trades"][:35]:  # 35 trades
                all_signals.append(
                    {
                        "whale_id": wid,
                        "side": t["side"],
                        "size_usd": float(t["size_usd"]),
                        "price": float(t["price"]),
                        "wr": wr,
                        "market_id": t["market_id"],
                    }
                )

        # Shuffle and take 35
        random.shuffle(all_signals)
        signals = all_signals[:35]

        for sig in signals:
            # Position size: 15% of balance
            position = balance * Decimal("0.15")

            # Simulate outcome based on whale's win rate
            if random.random() < sig["wr"]:
                # Win: 5-12% profit
                profit = position * Decimal(str(random.uniform(0.05, 0.12)))
                balance += profit
                wins += 1
                trade_log.append(("WIN", float(profit)))
            else:
                # Loss: 3-5%
                loss = position * Decimal(str(random.uniform(0.03, 0.05)))
                balance -= loss
                losses += 1
                trade_log.append(("LOSS", -float(loss)))

        results.append(
            {"balance": balance, "wins": wins, "losses": losses, "log": trade_log}
        )

    # Statistics
    avg_balance = sum(r["balance"] for r in results) / len(results)
    success_count = sum(1 for r in results if r["balance"] >= 125)
    avg_wr = sum(
        r["wins"] / (r["wins"] + r["losses"])
        for r in results
        if r["wins"] + r["losses"] > 0
    ) / len(results)
    best = max(r["balance"] for r in results)
    worst = min(r["balance"] for r in results)

    print(f"30 Simulations (7 days, 35 trades each):")
    print(f"  Average balance: ${avg_balance:.2f}")
    print(
        f"  Success rate (>= $125): {success_count}/30 ({success_count * 100 / 30:.0f}%)"
    )
    print(f"  Average WR: {avg_wr * 100:.1f}%")
    print(f"  Best: ${best:.2f}")
    print(f"  Worst: ${worst:.2f}")
    print()

    # Show one example run
    example = results[0]
    print(f"Example run:")
    print(f"  Final balance: ${example['balance']:.2f}")
    print(f"  Wins: {example['wins']}, Losses: {example['losses']}")
    print(f"  WR: {example['wins'] / (example['wins'] + example['losses']) * 100:.1f}%")

    # Check criteria
    print("\n=== Success Criteria ===")
    print(
        f"Balance >= $125: {'PASS' if avg_balance >= 125 else 'FAIL'} (${avg_balance:.2f})"
    )
    print(
        f"Win rate >= 60%: {'PASS' if avg_wr >= 0.60 else 'FAIL'} ({avg_wr * 100:.1f}%)"
    )
    print(
        f"Success rate >= 60%: {'PASS' if success_count / 30 >= 0.60 else 'FAIL'} ({success_count / 30 * 100:.0f}%)"
    )

    await conn.close()


asyncio.run(main())
