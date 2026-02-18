#!/usr/bin/env python3
"""Script to populate known whales into the database.

Usage:
    python scripts/add_whales_to_db.py

Environment:
    DATABASE_URL - PostgreSQL connection string
"""

import asyncio
import os
import sys
from decimal import Decimal
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import directly to avoid __init__ issues
from src.research.whale_tracker import WhaleTracker, WhaleStats


KNOWN_WHALES = [
    {
        "wallet_address": "0xdB27Bf2Ac5D428a9c63dbc914611036855a6c56E",
        "username": "DrPufferfish",
        "total_trades": 5000,
        "win_rate": Decimal("0.509"),
        "total_profit_usd": Decimal("2060000"),
        "avg_trade_size_usd": Decimal("500"),
        "risk_score": 5,
        "notes": "Diversified betting, transforms low-prob to high-prob events",
    },
    {
        "wallet_address": "0xee50a31c3f5a7c77824b12a941a54388a2827ed6",
        "username": "0xafEe",
        "total_trades": 200,
        "win_rate": Decimal("0.695"),
        "total_profit_usd": Decimal("929000"),
        "avg_trade_size_usd": Decimal("5000"),
        "risk_score": 3,
        "notes": "Low-frequency, pop culture predictions, highest WR among top 10",
    },
]


async def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        print("Usage: DATABASE_URL=postgresql://... python scripts/add_whales_to_db.py")
        sys.exit(1)

    tracker = WhaleTracker(database_url=database_url)

    print("=" * 60)
    print("Adding Known Whales to Database")
    print("=" * 60)

    for whale_data in KNOWN_WHALES:
        stats = WhaleStats(
            wallet_address=whale_data["wallet_address"],
            total_trades=whale_data["total_trades"],
            win_rate=whale_data["win_rate"],
            total_profit_usd=whale_data["total_profit_usd"],
            avg_trade_size_usd=whale_data["avg_trade_size_usd"],
            last_active_at=datetime.now(),
            risk_score=whale_data["risk_score"],
        )

        success = await tracker.save_whale(stats)

        if success:
            print(f"[OK] Added: {whale_data['username']}")
            print(f"   Address: {whale_data['wallet_address'][:20]}...")
            print(f"   WR: {float(whale_data['win_rate']) * 100:.1f}%")
            print(f"   Profit: ${float(whale_data['total_profit_usd']):,.0f}")
            print(f"   Risk Score: {whale_data['risk_score']}")
        else:
            print(f"[FAIL] Failed: {whale_data['username']}")

    print("=" * 60)
    print("Done!")

    await tracker.close()


if __name__ == "__main__":
    asyncio.run(main())
