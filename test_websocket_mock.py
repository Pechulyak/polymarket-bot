# -*- coding: utf-8 -*-
"""Тест WebSocket с локальным мок-сервером (без API ключа)."""

import sys

sys.path.insert(0, "src")

import asyncio
import json
import time
import subprocess
from data.ingestion.websocket_client import PolymarketWebSocket, WebSocketMessage


# Счетчики
messages_received = 0
start_time = None


def on_message(msg: WebSocketMessage):
    """Обработчик сообщений от мок-сервера."""
    global messages_received, start_time

    messages_received += 1
    current_time = time.time()

    if start_time is None:
        start_time = current_time

    elapsed = current_time - start_time

    print(
        f"\n📨 [{messages_received}] Сообщение #{messages_received} (через {elapsed:.2f}с)"
    )
    print(f"   Маркет: {msg.asset_id[:25]}...")

    data = msg.data
    if "price" in data:
        print(f"   💰 Цена: ${data['price']:.4f}")
    if "side" in data:
        print(f"   📊 Сторона: {data['side']}")
    if "size" in data:
        print(f"   📦 Размер: {data['size']:.2f}")

    if "market_data" in data:
        md = data["market_data"]
        print(f"   📝 {md.get('question', 'N/A')[:50]}...")
        print(
            f"   Bid: ${md.get('best_bid', 0):.4f} | Ask: ${md.get('best_ask', 0):.4f}"
        )


async def test_with_mock_server():
    """Тест с локальным мок-сервером."""
    print("=" * 70)
    print("ТЕСТ WebSocket С ЛОКАЛЬНЫМ МОК-СЕРВЕРОМ")
    print("=" * 70)
    print()

    # Запускаем мок-сервер в отдельном процессе
    print("1️⃣ Запускаем мок-сервер Polymarket...")
    print("   (в отдельном окне выполните: python mock_polymarket_server.py)")
    print()

    input("   Нажмите Enter когда сервер запущен...")
    print()

    # Создаем клиента с URL локального сервера
    print("2️⃣ Подключаемся к локальному серверу...")

    # Временно меняем URL на локальный
    original_url = PolymarketWebSocket.WS_URL
    PolymarketWebSocket.WS_URL = "ws://localhost:8765"

    ws = PolymarketWebSocket(
        on_message=on_message,
    )

    try:
        connected = await ws.connect()

        if not connected:
            print("❌ Не удалось подключиться!")
            print("   Убедитесь, что сервер запущен: python mock_polymarket_server.py")
            return

        print("✅ Подключено!")
        print()

        # Подписываемся на тестовые токены
        print("3️⃣ Подписываемся на тестовые токены...")
        test_tokens = [
            "0x1234567890abcdef1234567890abcdef12345678",
            "0xabcdef1234567890abcdef1234567890abcdef12",
        ]

        for i, token in enumerate(test_tokens, 1):
            print(f"   {i}. {token[:40]}...")

        await ws.subscribe_tokens(test_tokens)
        print(f"   ✅ Подписка отправлена")
        print()

        # Ждем сообщения
        print("4️⃣ Ждем сообщений 15 секунд...")
        print("-" * 70)

        await asyncio.sleep(15)

        print("-" * 70)
        print()

        # Статистика
        print("📊 СТАТИСТИКА:")
        print(f"   Всего сообщений получено: {messages_received}")

        if messages_received > 0:
            avg_delay = 15 / messages_received
            print(f"   Средняя частота: 1 сообщение каждые {avg_delay:.1f} сек")
            print()
            print("✅ WebSocket РАБОТАЕТ!")
            print("   Данные приходят в реальном времени.")
            print("   Клиент готов к использованию с реальным Polymarket API.")
        else:
            print()
            print("⚠️  Сообщений не было")
            print("   Проверьте, что сервер отправляет данные")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()

    finally:
        # Восстанавливаем оригинальный URL
        PolymarketWebSocket.WS_URL = original_url

        print()
        print("5️⃣ Отключаемся...")
        await ws.disconnect()
        print("✅ Отключено!")

    print()
    print("=" * 70)
    print("ТЕСТ ЗАВЕРШЕН")
    print("=" * 70)
    print()
    print("Для работы с реальным Polymarket:")
    print("1. Получите API ключ: https://polymarket.com/account/api-keys")
    print("2. Используйте PolymarketWebSocket с вашим ключом")
    print("3. Получайте реальные данные с wss://ws-subscriptions-clob.polymarket.com")


if __name__ == "__main__":
    try:
        asyncio.run(test_with_mock_server())
    except KeyboardInterrupt:
        print("\n\n⛔ Прервано пользователем")
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()
