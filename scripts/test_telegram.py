#!/usr/bin/env python3
"""Minimal Telegram connectivity test script."""

import os
import sys
import asyncio
import aiohttp
from dotenv import load_dotenv

# Load .env file
load_dotenv()


async def test_telegram() -> None:
    """Test Telegram bot token and send one test message."""
    # Try both possible token variable names
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_ALERT_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token:
        print("Telegram: not configured (token missing from .env)")
        return

    if not chat_id:
        print("Telegram: not configured (chat_id missing from .env)")
        return

    # Verify token by calling getMe
    try:
        async with aiohttp.ClientSession() as session:
            # First verify the token is valid
            async with session.get(
                f"https://api.telegram.org/bot{bot_token}/getMe",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    result = await resp.json()
                    error_desc = result.get("description", "Unknown error")
                    print(f"Telegram: failed")
                    print(f"Error: {error_desc}")
                    return

                result = await resp.json()
                if not result.get("ok"):
                    error_desc = result.get("description", "Unknown error")
                    print(f"Telegram: failed")
                    print(f"Error: {error_desc}")
                    return

                bot_info = result.get("result", {})
                bot_username = bot_info.get("username", "unknown")

            # Send one test message
            test_message = "🔔 Polymarket Bot - Connectivity Test"
            async with session.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": test_message
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    print(f"Telegram: ok")
                else:
                    result = await resp.json()
                    error_desc = result.get("description", "Unknown error")
                    print(f"Telegram: failed")
                    print(f"Error: {error_desc}")

    except aiohttp.ClientError as e:
        print(f"Telegram: failed")
        print(f"Error: {type(e).__name__}: {str(e)}")
    except Exception as e:
        print(f"Telegram: failed")
        print(f"Error: {type(e).__name__}: {str(e)}")


if __name__ == "__main__":
    asyncio.run(test_telegram())
