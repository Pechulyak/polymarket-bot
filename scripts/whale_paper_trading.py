import asyncio
import aiohttp
import asyncpg
import os
from decimal import Decimal
import random


async def main():
    db_url = os.getenv(
        "DATABASE_URL", "postgresql://postgres:password@localhost:5433/postgres"
    )
    conn = await asyncpg.connect(db_url)

    # Get quality whales
    whales = await conn.fetch(
        "SELECT id, wallet_address, win_rate, risk_score FROM whales WHERE win_rate >= 0.60"
    )
    print(f"Quality whales: {len(whales)}")

    # Record their trades
    total_trades = 0
    for whale in whales:
        addr = whale["wallet_address"]
        whale_id = whale["id"]

        url = "https://data-api.polymarket.com/trades"
        params = {"user": addr, "limit": 100}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    trades = await resp.json()
                    for t in trades:
                        size = float(t.get("size", 0))
                        price = float(t.get("price", 0))

                        await conn.execute(
                            """
                            INSERT INTO whale_trades (whale_id, market_id, side, size_usd, price, outcome, traded_at)
                            VALUES ($1, $2, $3, $4, $5, $6, to_timestamp($7))
                        """,
                            whale_id,
                            t.get("conditionId", ""),
                            t.get("side", "").lower(),
                            size * price,
                            price,
                            t.get("outcome", ""),
                            t.get("timestamp", 0),
                        )
                        total_trades += 1

    print(f"Recorded {total_trades} whale trades")

    # Paper trading simulation
    print("\n=== Paper Trading Simulation ===")

    initial = Decimal("100.00")
    results = []

    # Use highest WR whale
    best_whale = max(whales, key=lambda w: w["win_rate"])
    wr = float(best_whale["win_rate"])

    print(f"Using whale with {wr * 100:.0f}% win rate")

    for sim in range(30):
        balance = initial
        wins = 0
        losses = 0

        # 35 trades (7 days * 5/day)
        for i in range(35):
            position = balance * Decimal("0.15")

            if random.random() < wr:
                profit = position * Decimal(str(random.uniform(0.05, 0.12)))
                balance += profit
                wins += 1
            else:
                loss = position * Decimal(str(random.uniform(0.03, 0.05)))
                balance -= loss
                losses += 1

        results.append((balance, wins, losses))

    # Stats
    avg_balance = sum(r[0] for r in results) / len(results)
    success_count = sum(1 for r in results if r[0] >= 125)
    avg_wr = sum(r[1] for r in results) / sum(r[1] + r[2] for r in results)

    print(f"\n30 Simulations (35 trades each, {wr * 100:.0f}% WR):")
    print(f"  Average balance: ${avg_balance:.2f}")
    print(
        f"  Success rate (>= $125): {success_count}/30 ({success_count * 100 / 30:.0f}%)"
    )
    print(f"  Average WR: {avg_wr * 100:.1f}%")
    print(f"  Best: ${max(r[0] for r in results):.2f}")
    print(f"  Worst: ${min(r[0] for r in results):.2f}")

    await conn.close()


asyncio.run(main())
