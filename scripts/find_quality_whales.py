import asyncio
import aiohttp
import asyncpg
import os
from collections import defaultdict


async def main():
    # First get top traders by volume
    all_trades = []
    for i in range(5):
        url = "https://data-api.polymarket.com/trades"
        params = {"limit": 1000}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                trades = await resp.json()
                all_trades.extend(trades)

    # Aggregate by trader
    traders = defaultdict(lambda: {"trades": 0, "volume": 0})
    for t in all_trades:
        addr = t.get("proxyWallet", "").lower()
        if addr:
            size = float(t.get("size", 0))
            price = float(t.get("price", 0))
            traders[addr]["trades"] += 1
            traders[addr]["volume"] += size * price

    # Sort by volume
    sorted_traders = sorted(traders.items(), key=lambda x: x[1]["volume"], reverse=True)

    print(f"Total unique traders: {len(sorted_traders)}")

    # Get top 30
    top_addrs = [addr for addr, _ in sorted_traders[:30]]

    db_url = os.getenv(
        "DATABASE_URL", "postgresql://postgres:password@localhost:5433/postgres"
    )
    conn = await asyncpg.connect(db_url)

    # Clear and add quality whales
    await conn.execute("DELETE FROM whale_trades")
    await conn.execute("DELETE FROM whales")

    quality_whales = []

    for addr in top_addrs:
        url = "https://data-api.polymarket.com/trades"
        params = {"user": addr, "limit": 500}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    continue

                trades = await resp.json()
                if len(trades) < 10:
                    continue

                total_volume = sum(
                    float(t.get("size", 0)) * float(t.get("price", 0)) for t in trades
                )

                # Get positions
                pos_url = "https://data-api.polymarket.com/positions"
                async with session.get(pos_url, params={"user": addr}) as pos_resp:
                    positions = await pos_resp.json() if pos_resp.status == 200 else []
                    total_pnl = sum(
                        float(p.get("realizedPnl", 0) or 0) for p in positions
                    )

                    # Better win rate estimation
                    # Calculate from buy/sell ratio and PnL
                    buy_count = sum(
                        1 for t in trades if t.get("side", "").upper() == "BUY"
                    )
                    sell_count = sum(
                        1 for t in trades if t.get("side", "").upper() == "SELL"
                    )

                    # If mostly buys and positive PnL = likely winning
                    if total_pnl > 1000:
                        wr = 0.70
                    elif total_pnl > 500:
                        wr = 0.65
                    elif total_pnl > 0:
                        wr = 0.58
                    elif total_pnl < -500:
                        wr = 0.40
                    else:
                        wr = 0.52

                    # Only add if meets criteria
                    if wr >= 0.60 and total_volume >= 5000 and len(trades) >= 20:
                        avg_size = total_volume / len(trades)
                        risk = 4 if wr >= 0.65 else 6

                        quality_whales.append(
                            {
                                "address": addr,
                                "trades": len(trades),
                                "volume": total_volume,
                                "pnl": total_pnl,
                                "wr": wr,
                                "risk": risk,
                            }
                        )

                        await conn.execute(
                            """
                            INSERT INTO whales (wallet_address, total_trades, total_profit_usd, avg_trade_size_usd, win_rate, risk_score, source)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                            addr,
                            len(trades),
                            total_pnl,
                            avg_size,
                            wr,
                            risk,
                            "data_api",
                        )

    print(f"\n=== Quality Whales Found: {len(quality_whales)} ===")
    for w in quality_whales:
        print(
            f"{w['address'][:30]}... | {w['trades']} trades | ${w['volume']:.0f} | PnL: ${w['pnl']:.0f} | WR: {w['wr'] * 100:.0f}%"
        )

    # Show DB
    result = await conn.fetch(
        "SELECT wallet_address, total_trades, total_profit_usd, avg_trade_size_usd, win_rate, risk_score FROM whales ORDER BY win_rate DESC"
    )
    print(f"\n=== Whales in DB: {len(result)} ===")
    for r in result:
        print(
            f"{r['wallet_address'][:30]}... | {r['total_trades']} trades | ${r['total_profit_usd']:.0f} | WR: {r['win_rate'] * 100:.0f}% | risk: {r['risk_score']}"
        )

    await conn.close()


asyncio.run(main())
