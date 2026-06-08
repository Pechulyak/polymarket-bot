#!/usr/bin/env python3
"""
score_leaderboard_candidates.py

Дубль алгоритма src/strategy/roundtrip_builder.py для разового скоринга
leaderboard-кандидатов. Источник: leaderboard_candidate_trades.
Назначение: leaderboard_candidate_roundtrips + leaderboard_candidates.
Запускается вручную, без cron и Docker.

TODO: после завершения воронки — унифицировать с roundtrip_builder
      (параметризованный источник/назначение).
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import aiohttp
import asyncpg
from dotenv import load_dotenv

# Load .env
load_dotenv(Path(__file__).parent.parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
CLOB_API = "https://clob.polymarket.com/markets"


async def fetch_market(session: aiohttp.ClientSession, market_id: str, cache: dict) -> Optional[dict]:
    """Fetch market data from CLOB API with caching."""
    if market_id in cache:
        return cache[market_id]
    
    try:
        async with session.get(f"{CLOB_API}/{market_id}") as resp:
            if resp.status == 200:
                data = await resp.json()
                cache[market_id] = data
                return data
            else:
                print(f"[settlement] ERROR {resp.status} for market {market_id}")
                return None
    except Exception as e:
        print(f"[settlement] EXCEPTION market {market_id}: {e}")
        return None


async def process_candidate(
    session: aiohttp.ClientSession,
    conn: asyncpg.Connection,
    wallet: str,
    username: str,
) -> None:
    """Process single candidate: group trades into roundtrips, settlement, aggregate."""
    
    # Log field units before first candidate
    if wallet == "first_logged":
        rows = await conn.fetch(
            "SELECT side, size_usd, price, size_usd / price AS implied_contracts "
            "FROM leaderboard_candidate_trades LIMIT 5"
        )
        if rows:
            print(f"[scoring] Поля единиц: {dict(rows[0].keys())}")
            for r in rows:
                print(f"[scoring]   {r['side']}: size_usd={r['size_usd']}, price={r['price']}, "
                      f"implied_contracts={r['implied_contracts']}")
        return

    # Step A: Group trades into roundtrips
    groups = await conn.fetch(
        """
        SELECT
            wallet_address,
            market_id,
            outcome,
            SUM(CASE WHEN side='BUY'  THEN size_usd ELSE 0 END) AS open_size_usd,
            SUM(CASE WHEN side='BUY'  THEN size_usd * price ELSE 0 END)
                / NULLIF(SUM(CASE WHEN side='BUY' THEN size_usd ELSE 0 END), 0)
                AS open_price,
            MIN(CASE WHEN side='BUY'  THEN traded_at END) AS opened_at,
            SUM(CASE WHEN side='SELL' THEN size_usd ELSE 0 END) AS close_size_usd,
            SUM(CASE WHEN side='SELL' THEN size_usd * price ELSE 0 END)
                / NULLIF(SUM(CASE WHEN side='SELL' THEN size_usd ELSE 0 END), 0)
                AS close_price,
            MAX(CASE WHEN side='SELL' THEN traded_at END) AS closed_at,
            COUNT(CASE WHEN side='BUY'  THEN 1 END) AS buy_count,
            COUNT(CASE WHEN side='SELL' THEN 1 END) AS sell_count
        FROM leaderboard_candidate_trades
        WHERE wallet_address = $1
        GROUP BY wallet_address, market_id, outcome
        """,
        wallet,
    )
    
    if not groups:
        print(f"[scoring] {username}: нет групп")
        return
    
    market_cache = {}
    roundtrip_count = 0
    
    for group in groups:
        buy_count = group["buy_count"]
        sell_count = group["sell_count"]
        market_id = group["market_id"]
        outcome = group["outcome"]
        
        # Determine classification
        if buy_count > 0 and sell_count > 0:
            # SELL closes the position
            open_side = "BUY"
            close_side = "SELL"
            close_type = "SELL"
            close_price = group["close_price"]
            closed_at = group["closed_at"]
            net_pnl = (float(close_price) - float(group["open_price"])) * float(group["close_size_usd"])
            gross_pnl = net_pnl
            status = "CLOSED"
            pnl_status = "CONFIRMED"
        elif buy_count > 0 and sell_count == 0:
            # Need settlement
            open_side = "BUY"
            close_side = None
            close_price = None
            closed_at = None
            net_pnl = None
            gross_pnl = None
            status = "OPEN"
            pnl_status = "OPEN"
            close_type = "OPEN"
            
            # Settlement via CLOB API
            market_data = await fetch_market(session, market_id, market_cache)
            if market_data:
                tokens = market_data.get("tokens", [])
                closed = market_data.get("closed", False)
                
                # Find matching token by outcome (exact match)
                matched = False
                for token in tokens:
                    if token.get("outcome") == outcome:
                        matched = True
                        if closed:
                            winner = token.get("winner", False)
                            if winner:
                                close_type = "SETTLEMENT_WIN"
                                close_price = 1.0
                                net_pnl = (1.0 - float(group["open_price"])) * float(group["open_size_usd"])
                                gross_pnl = net_pnl
                                status = "CLOSED"
                                pnl_status = "CONFIRMED"
                            else:
                                close_type = "SETTLEMENT_LOSS"
                                close_price = 0.0
                                net_pnl = (0.0 - float(group["open_price"])) * float(group["open_size_usd"])
                                gross_pnl = net_pnl
                                status = "CLOSED"
                                pnl_status = "CONFIRMED"
                        else:
                            close_type = "OPEN"
                        break
                
                # Fallback: if no exact match, use winner=True token
                if not matched and closed:
                    winner_token = next((t for t in tokens if t.get("winner") == True), None)
                    if winner_token:
                        # We held one side - if winner exists, we win
                        close_type = "SETTLEMENT_WIN"
                        close_price = 1.0
                        net_pnl = (1.0 - float(group["open_price"])) * float(group["open_size_usd"])
                        gross_pnl = net_pnl
                        status = "CLOSED"
                        pnl_status = "CONFIRMED"
                    else:
                        # No winner token (shouldn't happen for closed market)
                        close_type = "OPEN"
                
                print(f"[settlement] {username} {market_id[:20]}... closed={closed}, matched={matched}")
            else:
                print(f"[settlement] {username} {market_id[:20]}... ERROR")
            
            await asyncio.sleep(0.05)
        else:
            # sell_count > 0, buy_count = 0: "headless" SELL
            open_side = None
            close_side = "SELL"
            close_price = group["close_price"]
            closed_at = group["closed_at"]
            net_pnl = None
            gross_pnl = None
            status = "OPEN"
            pnl_status = "OPEN"
            close_type = "OPEN"
        
        # Step C: Insert/update roundtrip
        await conn.execute(
            """
            INSERT INTO leaderboard_candidate_roundtrips (
                wallet_address, market_id, outcome,
                open_side, open_size_usd, open_price, opened_at,
                close_side, close_size_usd, close_price, closed_at, close_type,
                gross_pnl_usd, net_pnl_usd, pnl_status, status,
                created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, NOW(), NOW())
            ON CONFLICT (wallet_address, market_id, outcome) DO UPDATE SET
                open_side      = EXCLUDED.open_side,
                open_size_usd  = EXCLUDED.open_size_usd,
                open_price     = EXCLUDED.open_price,
                opened_at      = EXCLUDED.opened_at,
                close_side     = EXCLUDED.close_side,
                close_size_usd = EXCLUDED.close_size_usd,
                close_price    = EXCLUDED.close_price,
                closed_at      = EXCLUDED.closed_at,
                close_type     = EXCLUDED.close_type,
                gross_pnl_usd  = EXCLUDED.gross_pnl_usd,
                net_pnl_usd    = EXCLUDED.net_pnl_usd,
                pnl_status     = EXCLUDED.pnl_status,
                status         = EXCLUDED.status,
                updated_at     = NOW()
            """,
            wallet,
            market_id,
            outcome,
            open_side,
            group["open_size_usd"] or 0,
            group["open_price"],
            group["opened_at"],
            close_side,
            group["close_size_usd"] or 0,
            close_price,
            closed_at,
            close_type,
            gross_pnl,
            net_pnl,
            pnl_status,
            status,
        )
        roundtrip_count += 1
    
    # Step D: Aggregate and update leaderboard_candidates
    await conn.execute(
        """
        UPDATE leaderboard_candidates lc SET
            roundtrips_total   = agg.total,
            roundtrips_closed  = agg.closed,
            roundtrips_open    = agg.open,
            wins               = agg.wins,
            losses             = agg.losses,
            win_rate           = agg.wins::numeric / NULLIF(agg.closed, 0),
            calc_pnl_usd       = agg.calc_pnl,
            pnl_calc_method   = 'roundtrip+settlement',
            is_copyable       = NULL,
            updated_at        = NOW()
        FROM (
            SELECT
                wallet_address,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'CLOSED')         AS closed,
                COUNT(*) FILTER (WHERE status = 'OPEN')           AS open,
                COUNT(*) FILTER (WHERE status = 'CLOSED'
 AND net_pnl_usd > 0)           AS wins,
                COUNT(*) FILTER (WHERE status = 'CLOSED'
                                   AND net_pnl_usd <= 0)          AS losses,
                SUM(net_pnl_usd) FILTER (WHERE status = 'CLOSED') AS calc_pnl
            FROM leaderboard_candidate_roundtrips
            WHERE wallet_address = $1
            GROUP BY wallet_address
        ) agg
        WHERE lc.wallet_address = agg.wallet_address
        """,
        wallet,
    )
    
    # Get aggregated stats for logging
    stats = await conn.fetchrow(
        """
        SELECT
            COUNT(*)                                           AS total,
            COUNT(*) FILTER (WHERE status = 'CLOSED')         AS closed,
            COUNT(*) FILTER (WHERE status = 'OPEN')           AS open,
            COUNT(*) FILTER (WHERE status = 'CLOSED'
                               AND net_pnl_usd > 0)           AS wins,
            COUNT(*) FILTER (WHERE status = 'CLOSED'
                               AND net_pnl_usd <= 0)          AS losses
        FROM leaderboard_candidate_roundtrips
        WHERE wallet_address = $1
        """,
        wallet,
    )
    
    print(f"[roundtrip] {username}: total={stats['total']} closed={stats['closed']} "
          f"open={stats['open']} wins={stats['wins']} losses={stats['losses']}")


async def main() -> None:
    """Main entry point."""
    if not DATABASE_URL:
        print("[scoring] ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    # Connect to DB
    conn = await asyncpg.connect(DATABASE_URL)

    # Get candidates with is_copyable IS NULL
    candidates = await conn.fetch(
        """
        SELECT wallet_address, username
        FROM leaderboard_candidates
        WHERE is_copyable IS NULL
        ORDER BY leaderboard_rank
        """
    )
    
    if not candidates:
        print("[scoring] Нет кандидатов с is_copyable IS NULL")
        await conn.close()
        return
    
    print(f"[scoring] Обрабатываем {len(candidates)} кандидатов")
    
    # Log field units before first candidate
    first_row = await conn.fetchrow(
        "SELECT side, size_usd, price, size_usd / price AS implied_contracts "
        "FROM leaderboard_candidate_trades LIMIT 1"
    )
    if first_row:
        print(f"[scoring] Единицы size_usd: {first_row['size_usd']} (это USDC), "
              f"price: {first_row['price']} (это вероятность 0-1)")
        print(f"[scoring] implied_contracts = size_usd / price = {first_row['implied_contracts']}")
    
    # Prepare async HTTP session
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for i, candidate in enumerate(candidates, 1):
            wallet = candidate["wallet_address"]
            username = candidate["username"] or wallet[:10]
            print(f"[scoring] [{i}/{len(candidates)}] {username}")
            
            await process_candidate(session, conn, wallet, username)
            
            # Rate limit between candidates
            await asyncio.sleep(0.1)
    
    await conn.close()
    print("[scoring] Завершено")


if __name__ == "__main__":
    asyncio.run(main())
