# -*- coding: utf-8 -*-
"""Market Category Backfill Task.

Background task to backfill missing `market_category` values in the `whale_trades` table
using the existing `get_market_category()` function from market_category_cache.

Usage:
    # Direct call
    result = await backfill_market_categories("postgresql://...", batch_size=100)
    
    # Using settings from config
    from src.config.settings import settings
    result = await backfill_market_categories(settings.database_url, batch_size=100)
"""

import asyncio
from typing import Optional

import asyncpg
import structlog

from src.data.storage.market_category_cache import get_market_category
from src.config.settings import settings

logger = structlog.get_logger(__name__)


async def backfill_market_categories(
    database_url: Optional[str] = None,
    batch_size: int = 100,
) -> dict:
    """Backfill missing market_category values in whale_trades table.
    
    This function:
    1. SELECTs DISTINCT market_id FROM whale_trades WHERE market_category IS NULL
    2. For each unique market_id, calls get_market_category(market_id)
    3. UPDATEs whale_trades SET market_category = :cat WHERE market_id = :mid
       AND market_category IS NULL
    4. Sleeps 0.5s between API calls for rate limiting
    
    Args:
        database_url: PostgreSQL connection URL. If None, uses settings.database_url.
        batch_size: Number of unique market_ids to process in each batch.
    
    Returns:
        Dict with keys:
            - market_ids_processed: Number of unique market_ids processed
            - rows_updated: Total number of rows updated in whale_trades
    """
    # Use provided database_url or fall back to settings
    db_url = database_url or settings.database_url
    
    if not db_url or db_url == "sqlite:///:memory:":
        logger.error(
            "backfill_market_categories_no_db",
            database_url=db_url,
            message="Valid PostgreSQL database URL required for backfill",
        )
        return {"market_ids_processed": 0, "rows_updated": 0}
    
    logger.info(
        "backfill_market_categories_start",
        database_url=db_url[:30] + "..." if len(db_url) > 30 else db_url,
        batch_size=batch_size,
    )
    
    total_market_ids_processed = 0
    total_rows_updated = 0
    
    try:
        # Connect to PostgreSQL
        conn = await asyncpg.connect(db_url)
        
        try:
            while True:
                # Step 1: Get batch of DISTINCT market_ids where market_category is NULL, empty, or 'unknown'
                rows = await conn.fetch("""
                    SELECT market_id FROM (
                        SELECT DISTINCT market_id 
                        FROM whale_trades 
                        WHERE market_category IS NULL 
                           OR market_category = '' 
                           OR market_category = 'unknown'
                    ) t
                    ORDER BY RANDOM()
                    LIMIT $1
                """, batch_size)
                
                if not rows:
                    logger.info(
                        "backfill_market_categories_complete",
                        message="No more market_ids with NULL market_category",
                        market_ids_processed=total_market_ids_processed,
                        rows_updated=total_rows_updated,
                    )
                    break
                
                market_ids = [row["market_id"] for row in rows]
                logger.info(
                    "backfill_batch_start",
                    batch_size=len(market_ids),
                    total_processed=total_market_ids_processed,
                )
                
                # Step 2: Process each market_id
                for market_id in market_ids:
                    try:
                        # Call the existing get_market_category function with timeout
                        # This function has its own caching
                        try:
                            category = await asyncio.wait_for(
                                get_market_category(market_id),
                                timeout=10.0  # 10 second timeout per market_id
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                "backfill_market_category_timeout",
                                market_id=market_id[:20] + "..." if len(market_id) > 20 else market_id,
                                timeout_sec=10.0,
                            )
                            total_market_ids_processed += 1
                            await asyncio.sleep(0.5)  # Rate limit even on timeout
                            continue
                        
                        if category is None:
                            # API returned None - skip (don't write empty string)
                            logger.debug(
                                "backfill_market_category_skipped",
                                market_id=market_id[:20] + "..." if len(market_id) > 20 else market_id,
                                reason="API returned None",
                            )
                        else:
                            # Step 3: UPDATE whale_trades with the category
                            # Only update rows where market_category is NULL, empty, or 'unknown'
                            # (handle race condition where another process might have updated)
                            updated = await conn.execute("""
                                UPDATE whale_trades 
                                SET market_category = $1 
                                WHERE market_id = $2 
                                AND (market_category IS NULL OR market_category = '' OR market_category = 'unknown')
                            """, category, market_id)
                            
                            # Execute returns "UPDATE N" string, extract count
                            rows_affected = int(updated.split()[-1]) if updated else 0
                            total_rows_updated += rows_affected
                            
                            logger.debug(
                                "backfill_market_category_updated",
                                market_id=market_id[:20] + "..." if len(market_id) > 20 else market_id,
                                category=category,
                                rows_updated=rows_affected,
                            )
                        
                        total_market_ids_processed += 1
                        
                        # Rate limit: sleep 0.5s between API requests
                        await asyncio.sleep(0.5)
                        
                    except Exception as e:
                        logger.error(
                            "backfill_market_category_error",
                            market_id=market_id[:20] + "..." if len(market_id) > 20 else market_id,
                            error=str(e),
                        )
                        # Continue with next market_id - handle gracefully
                        continue
                
                logger.info(
                    "backfill_batch_complete",
                    batch_size=len(market_ids),
                    total_processed=total_market_ids_processed,
                    total_rows_updated=total_rows_updated,
                )
        
        finally:
            # Always close connection
            await conn.close()
    
    except Exception as e:
        logger.error(
            "backfill_market_categories_failed",
            error=str(e),
            market_ids_processed=total_market_ids_processed,
            rows_updated=total_rows_updated,
        )
        return {
            "market_ids_processed": total_market_ids_processed,
            "rows_updated": total_rows_updated,
            "error": str(e),
        }
    
    logger.info(
        "backfill_market_categories_finished",
        market_ids_processed=total_market_ids_processed,
        rows_updated=total_rows_updated,
    )
    
    return {
        "market_ids_processed": total_market_ids_processed,
        "rows_updated": total_rows_updated,
    }


async def backfill_roundtrip_categories(
    database_url: Optional[str] = None,
    batch_size: int = 100,
) -> dict:
    """Backfill missing market_category values in whale_trade_roundtrips table.
    
    This function:
    1. First tries to fill from whale_trades via JOIN (fast, no API)
    2. For remaining NULL market_ids, calls get_market_category() API
    3. Logs separately: updated_from_whales, updated_from_api, still_null
    
    Args:
        database_url: PostgreSQL connection URL. If None, uses settings.database_url.
        batch_size: Number of unique market_ids to process in each batch (for API part).
    
    Returns:
        Dict with keys:
            - updated_from_whales: Rows updated via JOIN from whale_trades
            - market_ids_from_api: Number of unique market_ids processed via API
            - rows_updated_from_api: Total rows updated via API
            - still_null: Rows still NULL after backfill
    """
    # Use provided database_url or fall back to settings
    db_url = database_url or settings.database_url
    
    if not db_url or db_url == "sqlite:///:memory:":
        logger.error(
            "roundtrip_categories_no_db",
            database_url=db_url,
            message="Valid PostgreSQL database URL required for backfill",
        )
        return {"updated_from_whales": 0, "market_ids_from_api": 0, "rows_updated_from_api": 0, "still_null": 0}
    
    logger.info(
        "roundtrip_categories_start",
        database_url=db_url[:30] + "..." if len(db_url) > 30 else db_url,
        batch_size=batch_size,
    )
    
    total_updated_from_whales = 0
    total_market_ids_from_api = 0
    total_rows_updated_from_api = 0
    
    try:
        conn = await asyncpg.connect(db_url)
        
        try:
            # Step 1: UPDATE from whale_trades via JOIN (fast, no API)
            logger.info("roundtrip_step1_join_start")
            result_join = await conn.execute("""
                UPDATE whale_trade_roundtrips rt
                SET market_category = wt.market_category
                FROM whale_trades wt
                WHERE rt.market_id = wt.market_id
                  AND rt.market_category IS NULL
                  AND wt.market_category IS NOT NULL
                  AND wt.market_category != 'unknown'
                  AND wt.market_category != ''
            """)
            rows_affected = int(result_join.split()[-1]) if result_join else 0
            total_updated_from_whales = rows_affected
            logger.info(
                "roundtrip_step1_join_complete",
                updated_from_whales=total_updated_from_whales,
            )
            
            # Step 2: Process remaining NULL market_ids via API
            while True:
                rows = await conn.fetch("""
                    SELECT market_id FROM (
                        SELECT DISTINCT rt.market_id 
                        FROM whale_trade_roundtrips rt
                        LEFT JOIN whale_trades wt ON rt.market_id = wt.market_id
                           AND wt.market_category IS NOT NULL 
                           AND wt.market_category != 'unknown'
                        WHERE rt.market_category IS NULL
                           AND wt.market_id IS NULL
                    ) t
                    ORDER BY RANDOM()
                    LIMIT $1
                """, batch_size)
                
                if not rows:
                    logger.info(
                        "roundtrip_step2_api_complete",
                        message="No more market_ids with NULL market_category",
                        market_ids_from_api=total_market_ids_from_api,
                        rows_updated_from_api=total_rows_updated_from_api,
                    )
                    break
                
                market_ids = [row["market_id"] for row in rows]
                logger.info(
                    "roundtrip_batch_start",
                    batch_size=len(market_ids),
                    total_processed=total_market_ids_from_api,
                )
                
                for market_id in market_ids:
                    try:
                        try:
                            category = await asyncio.wait_for(
                                get_market_category(market_id),
                                timeout=10.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                "roundtrip_category_timeout",
                                market_id=market_id[:20] + "..." if len(market_id) > 20 else market_id,
                            )
                            total_market_ids_from_api += 1
                            await asyncio.sleep(0.5)
                            continue
                        
                        if category is None:
                            logger.debug(
                                "roundtrip_category_skipped",
                                market_id=market_id[:20] + "..." if len(market_id) > 20 else market_id,
                            )
                        else:
                            updated = await conn.execute("""
                                UPDATE whale_trade_roundtrips 
                                SET market_category = $1 
                                WHERE market_id = $2 
                                AND market_category IS NULL
                            """, category, market_id)
                            
                            rows_affected = int(updated.split()[-1]) if updated else 0
                            total_rows_updated_from_api += rows_affected
                            
                            logger.debug(
                                "roundtrip_category_updated",
                                market_id=market_id[:20] + "..." if len(market_id) > 20 else market_id,
                                category=category,
                            )
                        
                        total_market_ids_from_api += 1
                        await asyncio.sleep(0.5)
                        
                    except Exception as e:
                        logger.error(
                            "roundtrip_category_error",
                            market_id=market_id[:20] + "..." if len(market_id) > 20 else market_id,
                            error=str(e),
                        )
                        continue
                
                logger.info(
                    "roundtrip_batch_complete",
                    batch_size=len(market_ids),
                    total_processed=total_market_ids_from_api,
                )
            
            # Step 3: Count still NULL
            still_null = await conn.fetchval("""
                SELECT COUNT(*) - COUNT(market_category) 
                FROM whale_trade_roundtrips 
                WHERE market_category IS NULL
            """)
            
        finally:
            await conn.close()
    
    except Exception as e:
        logger.error(
            "roundtrip_categories_failed",
            error=str(e),
            updated_from_whales=total_updated_from_whales,
            market_ids_from_api=total_market_ids_from_api,
            rows_updated_from_api=total_rows_updated_from_api,
        )
        return {
            "updated_from_whales": total_updated_from_whales,
            "market_ids_from_api": total_market_ids_from_api,
            "rows_updated_from_api": total_rows_updated_from_api,
            "still_null": 0,
            "error": str(e),
        }
    
    logger.info(
        "roundtrip_categories_finished",
        updated_from_whales=total_updated_from_whales,
        market_ids_from_api=total_market_ids_from_api,
        rows_updated_from_api=total_rows_updated_from_api,
        still_null=still_null,
    )
    
    return {
        "updated_from_whales": total_updated_from_whales,
        "market_ids_from_api": total_market_ids_from_api,
        "rows_updated_from_api": total_rows_updated_from_api,
        "still_null": still_null,
    }


async def main():
    """CLI entry point for running the backfill task."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Backfill missing market_category values in whale_trades"
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="PostgreSQL connection URL (default: from settings)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of market_ids to process per batch (default: 100)",
    )
    
    args = parser.parse_args()
    
    result = await backfill_market_categories(
        database_url=args.database_url,
        batch_size=args.batch_size,
    )
    
    print(f"\nBackfill Results:")
    print(f"  Market IDs processed: {result['market_ids_processed']}")
    print(f"  Rows updated: {result['rows_updated']}")
    
    if "error" in result:
        print(f"  Error: {result['error']}")
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))