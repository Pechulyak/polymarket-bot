import asyncio
import aiohttp
import asyncpg
import os


async def main():
    top_traders = [
        ("0x9d9346b36bfacf6858ae06c7401a72ad09162cf1", 500),
        ("0x1d0034134e339a309700ff2d34e99fa2d48b0313", 195),
        ("0x1979ae6b7e6534de9c4539d0c205e582ca637c9d", 115),
        ("0x492442eab586f242b53bda933fd5de859c8a3782", 10),
        ("0xf6963d4cdbb6f26d753bda303e9513132afb1b7d", 325),
    ]

    db_url = os.getenv(
        "DATABASE_URL", "postgresql://postgres:password@localhost:5433/postgres"
    )
    conn = await asyncpg.connect(db_url)

    for addr, known_trades in top_traders:
        print(f"\n=== {addr[:30]}... ===")

        url = "https://data-api.polymarket.com/trades"
        params = {"user": addr, "limit": 500}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    print(f"Error: {resp.status}")
                    continue

                trades = await resp.json()
                if not trades:
                    print("No trades")
                    continue

                total_volume = sum(
                    float(t.get("size", 0)) * float(t.get("price", 0)) for t in trades
                )
                buy_count = sum(1 for t in trades if t.get("side", "").upper() == "BUY")
                sell_count = sum(
                    1 for t in trades if t.get("side", "").upper() == "SELL"
                )

                print(f"Trades: {len(trades)} | Vol: ${total_volume:.0f}")
                print(f"BUY: {buy_count}, SELL: {sell_count}")

                pos_url = "https://data-api.polymarket.com/positions"
                async with session.get(pos_url, params={"user": addr}) as pos_resp:
                    positions = await pos_resp.json() if pos_resp.status == 200 else []

                    total_pnl = sum(
                        float(p.get("realizedPnl", 0) or 0) for p in positions
                    )
                    print(f"Realized PnL: ${total_pnl:.0f}")

                    if total_pnl > 500:
                        wr = 0.65
                    elif total_pnl > 0:
                        wr = 0.55
                    elif total_pnl < -500:
                        wr = 0.40
                    else:
                        wr = 0.50

                    print(f"Est. WR: {wr * 100:.0f}%")

                    if len(trades) >= 10 and total_volume >= 1000:
                        avg_size = total_volume / len(trades)
                        risk = 10 if wr < 0.55 else (7 if wr < 0.65 else 4)

                        await conn.execute(
                            """
                            INSERT INTO whales (wallet_address, total_trades, total_profit_usd, avg_trade_size_usd, win_rate, risk_score, source)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            ON CONFLICT (wallet_address) DO NOTHING
                        """,
                            addr,
                            len(trades),
                            total_pnl,
                            avg_size,
                            wr,
                            risk,
                            "data_api",
                        )
                        print(f"ADDED (vol: ${total_volume:.0f}, wr: {wr * 100:.0f}%)")

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
