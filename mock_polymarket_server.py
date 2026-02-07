# -*- coding: utf-8 -*-
"""Тестовый WebSocket сервер - имитация Polymarket для разработки.

Запустите этот сервер для тестирования бота без API ключа.
"""

import asyncio
import json
import random
import time
import websockets


# Тестовые маркеты 2026
TEST_MARKETS = [
    {
        "token_id": "0x1234567890abcdef1234567890abcdef12345678",
        "question": "Will BTC hit $100k by end of 2026?",
        "current_price": 0.65,
    },
    {
        "token_id": "0xabcdef1234567890abcdef1234567890abcdef12",
        "question": "Will Trump win 2026 midterms?",
        "current_price": 0.45,
    },
    {
        "token_id": "0x9876543210fedcba9876543210fedcba98765432",
        "question": "Will ETH ETF be approved in 2026?",
        "current_price": 0.78,
    },
]


async def mock_polymarket_server(websocket, path):
    """Обработчик WebSocket соединений."""
    print(f"[SERVER] Клиент подключен: {websocket.remote_address}")

    subscribed_tokens = set()

    try:
        async for message in websocket:
            try:
                data = json.loads(message)

                # Обработка подписки
                if data.get("type") == "market" or data.get("operation") == "subscribe":
                    tokens = data.get("assets_ids", [])
                    subscribed_tokens.update(tokens)
                    print(f"[SERVER] Подписка на {len(tokens)} токенов: {tokens}")

                    # Отправляем подтверждение
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "subscription_confirmed",
                                "tokens": tokens,
                                "timestamp": time.time(),
                            }
                        )
                    )

                # Обработка отписки
                elif data.get("operation") == "unsubscribe":
                    tokens = data.get("assets_ids", [])
                    for t in tokens:
                        subscribed_tokens.discard(t)
                    print(f"[SERVER] Отписка от {len(tokens)} токенов")

                # Обработка PING
                elif message == "PING":
                    await websocket.send("PONG")

            except json.JSONDecodeError:
                if message == "PING":
                    await websocket.send("PONG")
                else:
                    print(f"[SERVER] Неизвестное сообщение: {message}")

    except websockets.exceptions.ConnectionClosed:
        print(f"[SERVER] Клиент отключен")


async def generate_mock_data(websocket, subscribed_tokens):
    """Генерация фейковых данных о рынке."""
    while True:
        if subscribed_tokens:
            # Выбираем случайный токен
            token_id = random.choice(list(subscribed_tokens))

            # Генерируем случайное изменение цены
            market = next((m for m in TEST_MARKETS if m["token_id"] == token_id), None)
            if market:
                # Случайное движение цены
                price_change = random.uniform(-0.02, 0.02)
                new_price = max(0.01, min(0.99, market["current_price"] + price_change))
                market["current_price"] = new_price

                # Отправляем обновление
                message = {
                    "asset_id": token_id,
                    "channel": "market",
                    "price": round(new_price, 4),
                    "side": random.choice(["BUY", "SELL"]),
                    "size": round(random.uniform(10, 1000), 2),
                    "timestamp": time.time(),
                    "market_data": {
                        "question": market["question"],
                        "best_bid": round(new_price - 0.01, 4),
                        "best_ask": round(new_price + 0.01, 4),
                    },
                }

                try:
                    await websocket.send(json.dumps(message))
                    print(
                        f"[SERVER] Отправлено: {market['question'][:40]}... @ ${new_price:.4f}"
                    )
                except:
                    break

        # Ждем 1-3 секунды между сообщениями
        await asyncio.sleep(random.uniform(1, 3))


async def start_server():
    """Запуск WebSocket сервера."""
    print("=" * 70)
    print("ТЕСТОВЫЙ WebSocket СЕРВЕР (имитация Polymarket)")
    print("=" * 70)
    print()
    print("Поддерживаемые маркеты:")
    for i, market in enumerate(TEST_MARKETS, 1):
        print(f"  {i}. {market['question']}")
        print(f"     Token: {market['token_id'][:40]}...")
        print(f"     Price: ${market['current_price']:.2f}")
    print()
    print("Сервер запущен на: ws://localhost:8765")
    print("Для остановки нажмите Ctrl+C")
    print("=" * 70)
    print()

    # Запускаем сервер
    async with websockets.serve(mock_polymarket_server, "localhost", 8765):
        await asyncio.Future()  # Работаем вечно


if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("\n\n[SERVER] Остановлен пользователем")
