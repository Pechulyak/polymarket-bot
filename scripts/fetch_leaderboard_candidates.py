#!/usr/bin/env python3
"""
PIPE-045: Fetch leaderboard candidates + LP/HFT filters

Fetches top20 traders from Polymarket leaderboard, filters out LP market makers
and HFT burst traders, stores raw trades for scoring pipeline.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiohttp
import asyncpg
from dotenv import load_dotenv

# Load .env
load_dotenv(Path(__file__).parent.parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
LEADERBOARD_API = "https://data-api.polymarket.com/v1/leaderboard"
ACTIVITY_API = "https://data-api.polymarket.com/activity"


async def fetch_json(session: Optional[aiohttp.ClientSession], url: str, params: dict) -> Optional[list]:
    """Fetch JSON from API with error handling. Creates temp session if None."""
    try:
        if session is None:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as new_session:
                async with new_session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data if isinstance(data, list) else data.get("data", [])
                    else:
                        print(f"[fetch] ERROR {resp.status} for {url}")
                        return None
        else:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data if isinstance(data, list) else data.get("data", [])
                else:
                    print(f"[fetch] ERROR {resp.status} for {url}")
                    return None
    except Exception as e:
        print(f"[fetch] EXCEPTION {url}: {e}")
        return None


async def upsert_candidate(conn: asyncpg.Connection, candidate: dict) -> None:
    """Upsert candidate into leaderboard_candidates."""
    await conn.execute(
        """
        INSERT INTO leaderboard_candidates (
            wallet_address, username, leaderboard_period,
            leaderboard_rank, leaderboard_pnl_usd, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
        ON CONFLICT (wallet_address) DO UPDATE SET
            leaderboard_rank = EXCLUDED.leaderboard_rank,
            leaderboard_pnl_usd  = EXCLUDED.leaderboard_pnl_usd,
            username             = EXCLUDED.username,
            updated_at          = NOW()
        """,
        candidate["wallet_address"],
        candidate.get("username"),
        candidate.get("leaderboard_period", "ALL"),
        candidate["leaderboard_rank"],
        candidate.get("leaderboard_pnl_usd"),
    )


async def mark_lp_candidate(conn: asyncpg.Connection, wallet: str, username: str) -> None:
    """Mark candidate as LP market maker (but still fetch trades)."""
    await conn.execute(
        """
        UPDATE leaderboard_candidates SET
            is_lp = TRUE,
            filter_reason = 'lp_market_maker',
            updated_at = NOW()
        WHERE wallet_address = $1
        """,
        wallet,
    )
    print(f"[lp_filter] {username} — REWARD найден, is_lp=TRUE")


async def insert_trade(conn: asyncpg.Connection, trade: dict, wallet: str) -> None:
    """Insert trade into leaderboard_candidate_trades with dedup."""
    # Parse timestamp
    ts = trade.get("timestamp")
    if ts:
        traded_at = datetime.fromtimestamp(ts, tz=None)
    else:
        traded_at = datetime.utcnow()

    # Determine size_usd - prefer usdcSize if present
    size_usd = trade.get("usdcSize")
    if size_usd is None:
        size = trade.get("size")
        price = trade.get("price")
        if size is not None and price is not None:
            size_usd = float(size) * float(price)
        else:
            size_usd = 0.0

    await conn.execute(
        """
        INSERT INTO leaderboard_candidate_trades (
            wallet_address, tx_hash, market_id, outcome,
            side, size_usd, price, traded_at, created_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
        ON CONFLICT (tx_hash) DO NOTHING
        """,
        wallet,
        trade.get("transactionHash"),
        trade.get("conditionId"),
        trade.get("title"),  # outcome from activity API
        trade.get("side"),
        size_usd,
        trade.get("price"),
        traded_at,
    )


async def update_candidate_stats(conn: asyncpg.Connection, wallet: str) -> None:
    """Update trade statistics for candidate after fetching trades."""
    await conn.execute(
        """
        UPDATE leaderboard_candidates SET
            trades_fetched   = (
                SELECT COUNT(*) FROM leaderboard_candidate_trades
                WHERE wallet_address = $1
            ),
            date_first_trade = (
                SELECT MIN(traded_at) FROM leaderboard_candidate_trades
                WHERE wallet_address = $1
            ),
            date_last_trade  = (
                SELECT MAX(traded_at) FROM leaderboard_candidate_trades
                WHERE wallet_address = $1
            ),
            active_days      = (
                SELECT COUNT(DISTINCT DATE(traded_at))
                FROM leaderboard_candidate_trades
                WHERE wallet_address = $1
            ),
            fetched_at       = NOW(),
            updated_at      = NOW()
        WHERE wallet_address = $1
        """,
        wallet,
    )


async def check_lp_filter(session: aiohttp.ClientSession, wallet: str) -> bool:
    """Check if candidate has REWARD activity (is LP). Returns True if LP."""
    data = await fetch_json(
        session,
        ACTIVITY_API,
        {"user": wallet, "limit": 20},  # No type filter - get all activity
    )
    if data:
        for item in data:
            if item.get("type") == "REWARD":
                return True
    return False


async def fetch_trades_paginated(
    session: aiohttp.ClientSession,
    conn: asyncpg.Connection,
    wallet: str,
) -> int:
    """Fetch all trades for wallet with pagination. Returns total trades fetched."""
    total_trades = 0
    offset = 0
    max_trades = 10000

    while offset < max_trades:
        data = await fetch_json(
            session,
            ACTIVITY_API,
            {"type": "TRADE", "user": wallet, "limit": 500, "offset": offset},
        )
        if not data:
            break

        count = len(data)
        if count == 0:
            break

        # Log field names from first trade
        if offset == 0 and data:
            print(f"[fetch] Поля первой сделки: {list(data[0].keys())}")

        # Insert trades
        for trade in data:
            await insert_trade(conn, trade, wallet)

        total_trades += count
        print(f"[fetch] {wallet}: offset={offset}, fetched={count}, total={total_trades}")

        if count < 500:
            break

        offset += 500
        await asyncio.sleep(0.3)

    return total_trades


async def check_hft_filter(conn: asyncpg.Connection, wallet: str) -> tuple[int, int, float]:
    """Check HFT burst filter. Returns (peak_trades_per_15min, top_market_count, top_market_vol_pct)."""
    # Peak trades per 15-min window
    row = await conn.fetchrow(
        """
        SELECT MAX(cnt) AS peak_trades_per_15min FROM (
            SELECT
                date_trunc('hour', traded_at) +
                (EXTRACT(MINUTE FROM traded_at)::int / 15)
                    * interval '15 minutes' AS window_15,
                COUNT(*) AS cnt
            FROM leaderboard_candidate_trades
            WHERE wallet_address = $1
            GROUP BY window_15
        ) x
        """,
        wallet,
    )
    peak = row["peak_trades_per_15min"] or 0

    # Top market trade count
    row2 = await conn.fetchrow(
        """
        SELECT COUNT(*) AS cnt
        FROM leaderboard_candidate_trades
        WHERE wallet_address = $1
        GROUP BY market_id
        ORDER BY cnt DESC
        LIMIT 1
        """,
        wallet,
    )
    top_market_count = row2["cnt"] if row2 else 0

    # Top market volume percentage
    row3 = await conn.fetchrow(
        """
        WITH market_vols AS (
            SELECT SUM(size_usd) AS mkt_vol
            FROM leaderboard_candidate_trades
            WHERE wallet_address = $1
            GROUP BY market_id
            ORDER BY mkt_vol DESC
            LIMIT 1
        ),
        total_vol AS (
            SELECT SUM(size_usd) AS total
            FROM leaderboard_candidate_trades
            WHERE wallet_address = $1
        )
        SELECT
            mv.mkt_vol / NULLIF(tv.total, 0) * 100 AS top_vol_pct
        FROM market_vols mv, total_vol tv
        """,
        wallet,
    )
    top_market_vol_pct = float(row3["top_vol_pct"]) if row3 and row3["top_vol_pct"] else 0.0

    return peak, top_market_count, top_market_vol_pct


async def mark_hft_candidate(
    conn: asyncpg.Connection,
    wallet: str,
    username: str,
    peak: int,
) -> None:
    """Mark candidate as HFT burst."""
    await conn.execute(
        """
        UPDATE leaderboard_candidates SET
            is_hft_burst = TRUE,
            is_copyable = FALSE,
            filter_reason = 'hft_burst',
            updated_at = NOW()
        WHERE wallet_address = $1
        """,
        wallet,
    )
    print(f"[hft_filter] {username} — peak={peak}, ДРОП")


async def mark_passed_filter(
    conn: asyncpg.Connection,
    wallet: str,
    username: str,
    peak: int,
) -> None:
    """Mark candidate as passed filters (awaiting scoring)."""
    await conn.execute(
        """
        UPDATE leaderboard_candidates SET
            is_hft_burst = FALSE,
            is_lp = FALSE,
            is_copyable = NULL,
            updated_at = NOW()
        WHERE wallet_address = $1
        """,
        wallet,
    )
    print(f"[hft_filter] {username} — peak={peak}, ПРОШЁЛ")


async def process_candidate(
    session: aiohttp.ClientSession,
    conn: asyncpg.Connection,
    candidate: dict,
) -> None:
    """Process single candidate: LP filter → fetch trades → HFT filter."""
    wallet = candidate["wallet_address"]
    username = candidate.get("username") or wallet[:10]

    # Step B: LP filter (mark if found, but always proceed to Step C)
    is_lp = await check_lp_filter(session, wallet)
    if is_lp:
        await mark_lp_candidate(conn, wallet, username)
    # Always proceed to Step C regardless of LP status

    # Step C: Fetch full trade history
    total_trades = await fetch_trades_paginated(session, conn, wallet)
    if total_trades == 0:
        print(f"[fetch] {wallet}: нет сделок")
        # Still set is_copyable = NULL even with no trades
        await conn.execute(
            """
            UPDATE leaderboard_candidates SET
                is_copyable = NULL,
                updated_at = NOW()
            WHERE wallet_address = $1
            """,
            wallet,
        )
        return

    # Update candidate stats
    await update_candidate_stats(conn, wallet)

    # Step D: HFT filter - always set is_copyable = NULL
    peak, top_market_count, top_market_vol_pct = await check_hft_filter(conn, wallet)

    # Update HFT metrics and always set is_copyable = NULL
    await conn.execute(
        """
        UPDATE leaderboard_candidates SET
            peak_trades_per_15min = $2,
            top_market_trade_count = $3,
            top_market_vol_pct = $4,
            is_hft_burst = $5,
            is_copyable = NULL,
            updated_at = NOW()
        WHERE wallet_address = $1
        """,
        wallet,
        peak,
        top_market_count,
        top_market_vol_pct,
        peak > 20,
    )

    if peak > 20:
        print(f"[hft_filter] {username} — peak={peak}, ДРОП (is_copyable=NULL)")
    else:
        print(f"[hft_filter] {username} — peak={peak}, ПРОШЁЛ (is_copyable=NULL)")


async def main() -> None:
    """Main entry point."""
    if not DATABASE_URL:
        print("[leaderboard] ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    # Connect to DB
    conn = await asyncpg.connect(DATABASE_URL)

    # Fetch leaderboard
    print("[leaderboard] Fetching top 20 traders from leaderboard...")
    leaderboard_data = await fetch_json(
        None,
        LEADERBOARD_API,
        {"timePeriod": "ALL", "limit": 50},
    )
    if not leaderboard_data:
        print("[leaderboard] ERROR: No data from leaderboard API")
        await conn.close()
        sys.exit(1)

    # Log field names from first entry
    print(f"[leaderboard] Поля первой записи leaderboard: {list(leaderboard_data[0].keys())}")
    print(f"[leaderboard] pnl type: {type(leaderboard_data[0].get('pnl'))}")

    # Take top 20
    top_20 = leaderboard_data[:20]
    print(f"[leaderboard] Обрабатываем {len(top_20)} кандидатов")

    # Prepare async HTTP session
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for i, entry in enumerate(top_20, 1):
            wallet = entry.get("proxyWallet")
            if not wallet:
                print(f"[leaderboard] Пропуск записи {i}: нет wallet address")
                continue

            candidate = {
                "wallet_address": wallet,
                "username": entry.get("userName") or wallet[:10],
                "leaderboard_period": "ALL",
                "leaderboard_rank": i,
                "leaderboard_pnl_usd": entry.get("pnl") or 0,
            }

            # Upsert candidate
            await upsert_candidate(conn, candidate)
            print(f"[leaderboard] [{i}/20] {candidate['username']} — rank={i}, pnl={candidate['leaderboard_pnl_usd']}")

            # Process candidate (LP filter → trades → HFT filter)
            await process_candidate(session, conn, candidate)

            # Rate limit between candidates
            await asyncio.sleep(0.3)

    await conn.close()
    print("[leaderboard] Завершено")


if __name__ == "__main__":
    asyncio.run(main())
