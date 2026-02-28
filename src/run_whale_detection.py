# -*- coding: utf-8 -*-
"""Run Whale Detection - запускает автоматическое выявление китов.

Usage:
    python src/run_whale_detection.py
"""

import asyncio
import os
import sys
import time
from decimal import Decimal
from typing import List

if sys.platform == "win32":
    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

import aiohttp
from dotenv import load_dotenv

from research.whale_detector import WhaleDetector, DetectionConfig
from research.polymarket_data_client import PolymarketDataClient
from research.real_time_whale_monitor import RealTimeWhaleMonitor


async def fetch_active_token_ids(api_key: str = "") -> List[str]:
    """Fetch active market token IDs from Polymarket API.

    Args:
        api_key: Optional API key for Polymarket

    Returns:
        List of token IDs for WebSocket subscription
    """
    token_ids: List[str] = []

    try:
        import json

        try:
            import brotli  # noqa: F401 - for brotli decoding
        except ImportError:
            print("   ⚠️ Installing brotli...")
            import subprocess

            subprocess.run(
                [sys.executable, "-m", "pip", "install", "brotli"], check=True
            )
            import brotli  # noqa: F401

        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            print("   📡 Fetching events from gamma-api...")

            async with session.get(
                "https://gamma-api.polymarket.com/events",
                params={"closed": "false", "limit": "100"},
                headers=headers,
            ) as resp:
                if resp.status == 200:
                    events = await resp.json()
                    print(f"   📊 Found {len(events)} open events")
                else:
                    print(f"   ⚠️ Events API returned {resp.status}")
                    return []

            condition_ids = []

            for event in events:
                event_id = event.get("id")
                if not event_id:
                    continue

                async with session.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={"eventId": event_id, "closed": "false", "active": "true"},
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        markets = await resp.json()
                        markets = (
                            markets
                            if isinstance(markets, list)
                            else markets.get("markets", [])
                        )

                        for market in markets:
                            cond_id = market.get("conditionId")
                            if cond_id:
                                condition_ids.append(cond_id)

                            clob_tokens = market.get("clobTokenIds", "[]")
                            if clob_tokens:
                                try:
                                    ids = json.loads(clob_tokens)
                                    token_ids.extend(ids)
                                except Exception:
                                    pass

            print(
                f"   📊 Collected {len(token_ids)} token IDs, {len(condition_ids)} condition IDs"
            )

            if not token_ids and condition_ids:
                token_ids = condition_ids

    except ImportError:
        print("   ⚠️ brotli not installed")
    except Exception as e:
        print(f"   ⚠️ Failed to fetch markets: {e}")

    return token_ids


async def _fetch_condition_ids_fallback(api_key: str = "") -> List[str]:
    """Fallback: fetch using Gamma API with different approach."""
    token_ids: List[str] = []

    try:
        async with aiohttp.ClientSession() as session:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            url = "https://gamma-api.polymarket.com/markets"
            params = {"active": "true"}

            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    markets = await resp.json()
                    print(f"   📊 Found {len(markets)} markets (fallback)")

                    for market in markets[:20]:
                        condition_id = market.get("conditionId", "")
                        if condition_id:
                            token_ids.append(condition_id)

                    print(f"   📊 Collected {len(token_ids)} condition IDs")
                else:
                    print(f"   ⚠️ Fallback API returned {resp.status}")
    except Exception as e:
        print(f"   ⚠️ Fallback also failed: {e}")

    return token_ids

    return token_ids[:20]


async def main():
    print("=" * 50)
    print("🐋 Polymarket Whale Detection")
    print("=" * 50)

    load_dotenv()

    database_url = os.getenv(
        "DATABASE_URL", "postgresql://postgres:password@localhost:5433/postgres"
    )
    api_key = os.getenv("POLYMARKET_API_KEY", "")

    config = DetectionConfig(
        min_trade_size=Decimal("50"),
        min_trades_for_quality=1,
        daily_trade_threshold=5,
        quality_win_rate=Decimal("0.60"),
        quality_volume=Decimal("1000"),
    )

    print("\n📊 Config:")
    print(f"   Min trade size: ${config.min_trade_size}")
    print(f"   Min trades for quality: {config.min_trades_for_quality}")
    print(f"   Daily trade threshold: {config.daily_trade_threshold}")
    print(f"   Quality win rate: {config.quality_win_rate * 100}%")
    print(f"\n🔑 API Key: {'configured' if api_key else 'NOT SET'}")

    # Create Polymarket Data API client (provides trader addresses)
    polymarket_client = PolymarketDataClient()
    
    # Create detector with Data API client for whale detection
    detector = WhaleDetector(
        config=config,
        database_url=database_url,
        polymarket_client=polymarket_client,
        polymarket_poll_interval_seconds=60,
    )

    # Create WebSocket monitor with API credentials
    monitor = RealTimeWhaleMonitor(
        min_trade_size=Decimal("50"),
        database_url=database_url,
        tracked_whales=set(),
        api_key=api_key if api_key else None,
    )

    # Connect monitor to detector
    async def on_whale_signal(signal):
        result = await detector.process_trade(
            trader=signal.trader_address,
            market_id=signal.market_id,
            side=signal.side,
            size_usd=signal.size_usd,
            price=signal.price,
            timestamp=signal.timestamp,
        )
        if result:
            print(f"\n🐋 NEW WHALE DETECTED: {result.wallet_address[:10]}...")
            print(
                f"   WR: {result.win_rate * 100:.1f}% | Vol: ${result.total_volume:.0f} | Score: {result.risk_score}"
            )

    monitor.on_whale_signal = on_whale_signal

    print("\n🔄 Starting Whale Detector...")
    await detector.start()

    print("🔄 Fetching active markets...")
    token_ids = await fetch_active_token_ids(api_key)

    print("🔄 Connecting to Polymarket WebSocket...")
    try:
        await monitor.start(token_ids=token_ids if token_ids else None)
        if token_ids:
            print(
                f"   ✅ WebSocket connected and subscribed to {len(token_ids)} markets!"
            )
        else:
            print("   ✅ WebSocket connected!")
    except Exception as e:
        print(f"   ⚠️ WebSocket failed: {e}")
        print("   💡 Running in demo mode with test data...")

        # Add demo trades
        test_whale = "0x742d35Cc6634C0532925a3b844Bc9e7595f12345"
        now = time.time()
        for i in range(6):
            await detector.process_trade(
                trader=test_whale,
                market_id="0x1234567890abcdef",
                side="buy",
                size_usd=Decimal("100"),
                price=Decimal("0.55"),
                timestamp=now - (i * 100),
                is_winner=i < 4,
            )
        print("   Added 6 test trades for demo")

    print("\n✅ Whale Detector is running!")
    print("   Press Ctrl+C to stop\n")

    try:
        while True:
            await asyncio.sleep(10)
            stats = detector.get_stats()
            quality = detector.get_quality_whales()

            print(f"[{time.time():.0f}] Stats:")
            print(f"   Total tracked: {stats['total_tracked']}")
            print(f"   Quality whales: {stats['quality_whales']}")

            if quality:
                print("   🐋 Quality Whales:")
                for whale in quality[:5]:
                    print(
                        f"      {whale.wallet_address[:10]}... | WR: {whale.win_rate * 100:.1f}% | Vol: ${whale.total_volume:.0f}"
                    )
            print()

    except KeyboardInterrupt:
        print("\n\n🛑 Stopping...")
        await detector.stop()
        if monitor.is_running():
            await monitor.stop()
        print("✅ Stopped")


if __name__ == "__main__":
    asyncio.run(main())
