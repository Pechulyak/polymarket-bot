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
                # Step 1: Get batch of DISTINCT market_ids where market_category IS NULL
                rows = await conn.fetch("""
                    SELECT DISTINCT market_id 
                    FROM whale_trades 
                    WHERE market_category IS NULL 
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
                        # Call the existing get_market_category function
                        # This function has its own caching
                        category = await get_market_category(market_id)
                        
                        if category is None:
                            # API returned None - skip (don't write empty string)
                            logger.debug(
                                "backfill_market_category_skipped",
                                market_id=market_id[:20] + "..." if len(market_id) > 20 else market_id,
                                reason="API returned None",
                            )
                        else:
                            # Step 3: UPDATE whale_trades with the category
                            # Only update rows where market_category IS NULL
                            # (handle race condition where another process might have updated)
                            updated = await conn.execute("""
                                UPDATE whale_trades 
                                SET market_category = $1 
                                WHERE market_id = $2 
                                AND market_category IS NULL
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