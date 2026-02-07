# -*- coding: utf-8 -*-
"""Пример использования PolymarketClient."""

import sys

sys.path.insert(0, "src")

import asyncio
from execution.polymarket.client import PolymarketClient


async def main():
    """Главная функция примера."""
    print("Запуск PolymarketClient...")
    client = PolymarketClient()

    try:
        # Получить все активные маркеты
        print("\nПолучаем список маркетов...")
        markets = await client.get_markets()
        print(f"Найдено {len(markets)} маркетов")

        if markets:
            # Показать первые 3 маркета
            print("\nПервые 3 маркета:")
            for i, market in enumerate(markets[:3], 1):
                print(f"  {i}. {market.get('question', 'N/A')}")

        # Показать статистику
        print("\nСтатистика клиента:")
        stats = client.get_stats()
        print(f"  Rate limit: {stats['rate_limit']} req/min")
        print(f"  Requests in window: {stats['requests_in_window']}")
        print(f"  Remaining: {stats['remaining_requests']}")

    except Exception as e:
        print(f"Ошибка: {e}")

    finally:
        await client.close()
        print("\nКлиент закрыт.")


if __name__ == "__main__":
    asyncio.run(main())
