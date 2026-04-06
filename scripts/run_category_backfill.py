#!/usr/bin/env python3
"""Category backfill — запуск через cron.

Cron: 0 */2 * * * cd /root/polymarket-bot && python3 scripts/run_category_backfill.py >> logs/category_backfill.log 2>&1
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

# Add src to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

# Load .env file
load_dotenv()

from src.data.storage.category_backfill import backfill_market_categories


async def main():
    """Run the category backfill task."""
    # Get database URL from environment, fallback to localhost:5433
    db_url = os.environ.get("DATABASE_URL", "postgresql://postgres:password@localhost:5433/polymarket")
    
    print(f"Starting category backfill with database: {db_url[:30]}...")
    
    result = await backfill_market_categories(database_url=db_url, batch_size=500)
    
    print(f"Backfill complete: {result}")
    return result


if __name__ == "__main__":
    result = asyncio.run(main())
    print(f"Result: {result}")