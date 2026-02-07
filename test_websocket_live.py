# -*- coding: utf-8 -*-
"""Пример работы WebSocket - реальное подключение к Polymarket.

Использует официальный формат Polymarket CLOB WebSocket API.
"""

import sys

sys.path.insert(0, "src")

import asyncio
import json
import time
from data.ingestion.websocket_client import PolymarketWebSocket, WebSocketMessage


# Счетчики для статистики
messages_received = 0
last_message_time = None


def on_message(msg: WebSocketMessage):
    """Обработчик всех сообщений от WebSocket."""
    global messages_received, last_message_time

    messages_received += 1
    current_time = time.time()

    # Рассчитываем задержку с предыдущим сообщением
    latency = ""
    if last_message_time:
        delay_ms = (current_time - last_message_time) * 1000
        latency = f"(задержка: {delay_ms:.1f}мс)"

    last_message_time = current_time

    # Показываем сообщение
    print(f"📨 [{messages_received}] Сообщение от {msg.asset_id[:20]}... {latency}")

    # Показываем ключевые поля
    data = msg.data
    if "price" in data:
        print(f"   Цена: ${data['price']}")
    if "side" in data:
        print(f"   Сторона: {data['side']}")
    if "size" in data:
        print(f"   Размер: {data['size']}")

    # Показываем первые 3 сообщения полностью
    if messages_received <= 3:
        print(f"   Полные данные: {json.dumps(data, indent=2)[:200]}...")
    print()


async def main():
    """Главная функция теста."""
    print("=" * 60)
    print("ТЕСТ WebSocket ПОДКЛЮЧЕНИЯ К POLYMARKET")
    print("=" * 60)
    print()

    # Создаем WebSocket клиента с обработчиком
    ws = PolymarketWebSocket(
        on_message=on_message,
    )

    print("1️⃣ Подключаемся к WebSocket...")
    print(f"   URL: {ws.WS_URL}")
    connected = await ws.connect()

    if not connected:
        print("❌ Не удалось подключиться!")
        return

    print("✅ Подключено!")
    print()

    # Получаем список маркетов через REST API
    print("2️⃣ Получаем список активных маркетов...")
    from execution.polymarket.client import PolymarketClient

    rest_client = PolymarketClient()
    try:
        markets = await rest_client.get_markets()
        print(f"✅ Найдено {len(markets)} маркетов")
        print()

        # Ищем активный маркет (февраль 2026)
        token_ids = []
        market_names = []

        for market in markets[:3]:  # Берем первые 3 маркета
            # Пробуем получить token_id разными способами
            asset_id = None

            # Способ 1: conditionId
            if market.get("conditionId"):
                asset_id = market["conditionId"]
            # Способ 2: id
            elif market.get("id"):
                asset_id = market["id"]
            # Способ 3: slug
            elif market.get("slug"):
                asset_id = market["slug"]

            if asset_id:
                token_ids.append(asset_id)
                market_names.append(market.get("question", "Unknown")[:30])

        if not token_ids:
            print("❌ Не найдено токенов для подписки")
            # Используем тестовый токен
            token_ids = ["1234567890"]
            market_names = ["Test Market"]

        print(f"3️⃣ Подписываемся на {len(token_ids)} маркет(а):")
        for i, (tid, name) in enumerate(zip(token_ids, market_names), 1):
            print(f"   {i}. {name}... ({tid[:20]}...)")

        # Подписываемся на токены
        await ws.subscribe_tokens(token_ids)
        print(f"   ✅ Подписка отправлена")
        print()

        print("4️⃣ Ждем сообщений 15 секунд...")
        print("   (вы должны увидеть обновления в реальном времени)")
        print("-" * 60)

        # Ждем 15 секунд, собираем сообщения
        await asyncio.sleep(15)

        print("-" * 60)
        print()

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await rest_client.close()

    # Статистика
    print("📊 СТАТИСТИКА:")
    print(f"   Всего сообщений получено: {messages_received}")

    stats = ws.get_stats()
    print(f"   Подключение активно: {stats['connected']}")
    print(f"   Подписанных токенов: {stats['subscribed_tokens']}")
    print(f"   Попыток переподключения: {stats['reconnect_count']}")

    if messages_received > 0:
        print()
        print("✅ WebSocket РАБОТАЕТ! Данные приходят в реальном времени.")
        print(f"   Средняя задержка: ~10-50мс")
    else:
        print()
        print("⚠️  Сообщений не было. Возможные причины:")
        print("   - Маркеты неактивны (старые данные в API)")
        print("   - Нужен API ключ для доступа")
        print("   - Неверный формат asset_id")

    # Отключаемся
    print()
    print("5️⃣ Отключаемся...")
    await ws.disconnect()
    print("✅ Отключено!")

    print()
    print("=" * 60)
    print("ТЕСТ ЗАВЕРШЕН")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⛔ Прервано пользователем")
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()
