#!/usr/bin/env python3
"""
PIPE-045 / PIPE-049 / PIPE-051: Fetch leaderboard candidates + LP/HFT filters (category-based)

Fetches top-N traders per leaderboard category (timePeriod=MONTH, orderBy=PNL),
deduplicates wallets across categories, filters out LP market makers
and HFT burst traders, stores raw trades for scoring pipeline.

PIPE-049: OVERALL and SPORTS categories excluded (recon 2026-07-11:
OVERALL top-10 identical to SPORTS top-10; sports profile is non-copyable).

PIPE-051: HFT-фильтр ужесточён — is_hft_burst теперь срабатывает только если
peak_trades_per_15min > 20 AND burst_trade_pct > 50.0 (доля сделок в
burst-окнах от 90d total). Одинокий всплеск больше не флагует обычного
трейдера. Детали и пороги — в scratchpad/pipe051_burst_analysis_report.md.
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

# PIPE-049: категории leaderboard. OVERALL и SPORTS исключены намеренно
# (OVERALL == SPORTS по составу; спортивный профиль некопируемый).
CATEGORIES = [
    "POLITICS",
    "ESPORTS",
    "CRYPTO",
    "CULTURE",
    "MENTIONS",
    "WEATHER",
    "ECONOMICS",
    "TECH",
    "FINANCE",
]
TOP_N_PER_CATEGORY = 5
TIME_PERIOD = "MONTH"


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
            leaderboard_rank, leaderboard_pnl_usd,
            best_category, categories, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
        ON CONFLICT (wallet_address) DO UPDATE SET
            leaderboard_rank    = EXCLUDED.leaderboard_rank,
            leaderboard_pnl_usd = EXCLUDED.leaderboard_pnl_usd,
            username            = EXCLUDED.username,
            leaderboard_period  = EXCLUDED.leaderboard_period,
            best_category       = EXCLUDED.best_category,
            categories          = EXCLUDED.categories,
            updated_at          = NOW()
        """,
        candidate["wallet_address"],
        candidate.get("username"),
        candidate.get("leaderboard_period", TIME_PERIOD),
        candidate["leaderboard_rank"],
        candidate.get("leaderboard_pnl_usd"),
        candidate.get("best_category"),
        candidate.get("categories"),
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
        trade.get("outcome"),  # Yes/No from activity API
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
    """Fetch all trades for wallet with pagination. Returns total trades fetched.

    PIPE-051: на HTTP-ошибку (fetch_json вернул None) делаем до 2 повторных
    попыток с паузой 1 сек; если не помогло — печатаем WARNING и break,
    чтобы остаток истории кошелька не терялся молча, но и валидация
    дальнейших кошельков не падала.
    """
    total_trades = 0
    offset = 0
    max_trades = 10000

    while offset < max_trades:
        # PIPE-051: различаем data is None (ошибка) и data == [] (конец истории)
        data = None
        for attempt in range(3):  # 1 основная + 2 повтора
            data = await fetch_json(
                session,
                ACTIVITY_API,
                {"type": "TRADE", "user": wallet, "limit": 500, "offset": offset},
            )
            if data is not None:
                break
            if attempt < 2:
                await asyncio.sleep(1.0)
        if data is None:
            print(f"[fetch] WARNING: {wallet} — история обрезана на "
                  f"offset={offset}, HFT-метрики могут быть неполными")
            break
        if not data:
            break

        # Filter out trades older than 90 days
        cutoff = datetime.utcnow().timestamp() - (90 * 24 * 3600)
        data = [t for t in data if t.get("timestamp", 0) >= cutoff]
        if not data:
            break

        count = len(data)

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


async def check_hft_filter(conn: asyncpg.Connection, wallet: str) -> tuple[int, int, float, Optional[float]]:
    """Check HFT burst filter.

    Returns (peak_trades_per_15min, top_market_count, top_market_vol_pct, burst_trade_pct).

    PIPE-051: burst_trade_pct — доля сделок кошелька, попавших в "burst-окна"
    (15-мин интервалы с count > 20), от общего числа сделок за 90 дней.
    Эмпирический разрыв: 7 явных не-ботов — 0.97-31.25%, 5 явных ботов —
    78.73-99.44%. Порог 50% лежит в разрыве с запасом. Если total trades = 0,
    возвращается None (фильтр не применим).
    """
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

    # PIPE-051: burst_trade_pct — (сумма cnt по окнам с cnt > 20) / total_trades * 100
    burst_row = await conn.fetchrow(
        """
        WITH windows AS (
            SELECT
                date_trunc('hour', traded_at) +
                (EXTRACT(MINUTE FROM traded_at)::int / 15)
                    * interval '15 minutes' AS window_15,
                COUNT(*) AS cnt
            FROM leaderboard_candidate_trades
            WHERE wallet_address = $1
            GROUP BY window_15
        ),
        totals AS (
            SELECT COUNT(*) AS total FROM leaderboard_candidate_trades
            WHERE wallet_address = $1
        )
        SELECT
            (SELECT COALESCE(SUM(cnt), 0) FROM windows WHERE cnt > 20) AS burst_trades,
            (SELECT total FROM totals) AS total_trades
        """,
        wallet,
    )
    if burst_row is None or not burst_row["total_trades"]:
        burst_trade_pct: Optional[float] = None
    else:
        burst_trade_pct = round(
            float(burst_row["burst_trades"]) / float(burst_row["total_trades"]) * 100,
            2,
        )

    return peak, top_market_count, top_market_vol_pct, burst_trade_pct


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
    peak, top_market_count, top_market_vol_pct, burst_trade_pct = await check_hft_filter(conn, wallet)

    # PIPE-051: is_hft_burst срабатывает только если peak > 20 AND burst_trade_pct > 50.0.
    # Одинокий всплеск (peak чуть выше 20 при burst_trade_pct < 50%) больше не флагует обычного
    # трейдера как HFT. Если burst_trade_pct == None (нет сделок) — тоже не флагуем.
    is_hft_burst = (
        peak > 20
        and burst_trade_pct is not None
        and burst_trade_pct > 50.0
    )

    # Update HFT metrics and always set is_copyable = NULL
    await conn.execute(
        """
        UPDATE leaderboard_candidates SET
            peak_trades_per_15min = $2,
            top_market_trade_count = $3,
            top_market_vol_pct = $4,
            burst_trade_pct = $5,
            is_hft_burst = $6,
            is_copyable = NULL,
            updated_at = NOW()
        WHERE wallet_address = $1
        """,
        wallet,
        peak,
        top_market_count,
        top_market_vol_pct,
        burst_trade_pct,
        is_hft_burst,
    )

    if is_hft_burst:
        print(f"[hft_filter] {username} — peak={peak}, burst_pct={burst_trade_pct}, ДРОП (is_copyable=NULL)")
    else:
        print(f"[hft_filter] {username} — peak={peak}, burst_pct={burst_trade_pct}, ПРОШЁЛ (is_copyable=NULL)")


async def main() -> None:
    """Main entry point."""
    if not DATABASE_URL:
        print("[leaderboard] ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    # Connect to DB
    conn = await asyncpg.connect(DATABASE_URL)

    # Обнуляем leaderboard_rank для непроверенных кандидатов перед новым прогоном
    await conn.execute(
        "UPDATE leaderboard_candidates "
        "SET leaderboard_rank = NULL, best_category = NULL, categories = NULL "
        "WHERE reviewed_at IS NULL"
    )
    print("[leaderboard] Сброшены leaderboard_rank/category для непроверенных кандидатов")

    # PIPE-049: Fetch top-N per category, dedup across categories
    print(f"[leaderboard] Fetching top-{TOP_N_PER_CATEGORY} per category "
          f"({len(CATEGORIES)} categories, timePeriod={TIME_PERIOD}, orderBy=PNL)...")

    # wallet -> {username, hits: [(category, rank, pnl)]}
    collected: dict[str, dict[str, Any]] = {}

    for category in CATEGORIES:
        data = await fetch_json(
            None,
            LEADERBOARD_API,
            {
                "category": category,
                "timePeriod": TIME_PERIOD,
                "orderBy": "PNL",
                "limit": TOP_N_PER_CATEGORY,
            },
        )
        if not data:
            print(f"[leaderboard] WARN: нет данных для категории {category}, пропуск")
            await asyncio.sleep(0.3)
            continue

        print(f"[leaderboard] {category}: {len(data)} записей")

        for rank, entry in enumerate(data, 1):
            wallet = entry.get("proxyWallet")
            if not wallet:
                print(f"[leaderboard] {category}: пропуск rank={rank}, нет wallet")
                continue
            pnl = entry.get("pnl") or 0
            if wallet not in collected:
                collected[wallet] = {
                    "username": entry.get("userName") or wallet[:10],
                    "hits": [],
                }
            collected[wallet]["hits"].append((category, rank, pnl))

        await asyncio.sleep(0.3)

    if not collected:
        print("[leaderboard] ERROR: ни одна категория не вернула данных")
        await conn.close()
        sys.exit(1)

    total = len(collected)
    multi_cat = sum(1 for c in collected.values() if len(c["hits"]) > 1)
    print(f"[leaderboard] Уникальных кандидатов после дедупа: {total} "
          f"(в 2+ категориях: {multi_cat})")

    # Prepare async HTTP session
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for i, (wallet, info) in enumerate(collected.items(), 1):
            # best category = максимальный pnl среди попаданий
            best_cat, best_rank, best_pnl = max(info["hits"], key=lambda h: h[2])
            categories_csv = ",".join(f"{c}:{r}" for c, r, _ in info["hits"])

            candidate = {
                "wallet_address": wallet,
                "username": info["username"],
                "leaderboard_period": TIME_PERIOD,
                "leaderboard_rank": best_rank,
                "leaderboard_pnl_usd": best_pnl,
                "best_category": best_cat,
                "categories": categories_csv,
            }

            # Upsert candidate
            await upsert_candidate(conn, candidate)
            print(f"[leaderboard] [{i}/{total}] {candidate['username']} — "
                  f"best={best_cat} rank={best_rank}, pnl={best_pnl}, cats=[{categories_csv}]")

            # Process candidate (LP filter → trades → HFT filter)
            await process_candidate(session, conn, candidate)

            # Rate limit between candidates
            await asyncio.sleep(0.3)

    await conn.close()
    print("[leaderboard] Завершено")


if __name__ == "__main__":
    asyncio.run(main())
