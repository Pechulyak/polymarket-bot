# -*- coding: utf-8 -*-
"""Простой тест WebSocket - просто слушаем что приходит."""

import sys

sys.path.insert(0, "src")

import asyncio
import websockets
import json


async def test_websocket():
    """Простой тест - подключаемся и слушаем."""
    url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    print("Подключаемся к WebSocket...")
    print(f"URL: {url}")
    print()

    try:
        async with websockets.connect(url) as ws:
            print("✅ Подключено!")
            print("Слушаем сообщения 10 секунд...")
            print("-" * 60)

            # Слушаем 10 секунд
            for i in range(10):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    print(f"[{i + 1}] Получено: {msg[:100]}...")

                    # Пробуем распарсить
                    try:
                        data = json.loads(msg)
                        print(f"    JSON: {json.dumps(data, indent=2)[:200]}")
                    except:
                        print(f"    (не JSON)")

                except asyncio.TimeoutError:
                    print(f"[{i + 1}] Таймаут (нет сообщений)")

            print("-" * 60)
            print("Закрываем соединение...")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_websocket())
