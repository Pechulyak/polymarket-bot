# -*- coding: utf-8 -*-
"""Получение актуальных токенов для WebSocket (февраль 2026) с фильтрацией по дате."""

import sys

sys.path.insert(0, "src")

import asyncio
import json
from datetime import datetime
from execution.polymarket.client import PolymarketClient


async def get_active_tokens():
    """Получить активные токены из API с фильтрацией по дате."""
    print("Получаем список активных маркетов...")
    print("Фильтр: дата окончания > 2026-02-07")
    print("=" * 70)

    client = PolymarketClient()

    try:
        # Получаем активные маркеты
        markets = await client.get_markets(active_only=True)
        print(f"\n✅ Получено {len(markets)} маркетов\n")

        # Текущая дата
        now = datetime.now()
        print(f"Текущая дата: {now.strftime('%Y-%m-%d')}\n")

        # Ищем маркеты с будущей датой окончания
        active_tokens = []
        future_markets = []

        for market in markets:
            end_date_str = market.get("endDate", "")
            question = market.get("question", "N/A")

            try:
                # Парсим дату окончания
                if end_date_str:
                    end_date = datetime.fromisoformat(
                        end_date_str.replace("Z", "+00:00").replace("+00:00", "")
                    )

                    # Проверяем, что дата в будущем
                    if end_date > now:
                        future_markets.append(market)

                        # Получаем токены
                        tokens = market.get("tokens", [])
                        condition_id = market.get("conditionId", "")
                        market_id = market.get("id", "N/A")

                        if tokens:
                            for token in tokens:
                                token_id = token.get("token_id", "")
                                outcome = token.get("outcome", "N/A")
                                if token_id:
                                    active_tokens.append(
                                        {
                                            "question": question,
                                            "token_id": token_id,
                                            "outcome": outcome,
                                            "condition_id": condition_id,
                                            "market_id": market_id,
                                            "end_date": end_date_str,
                                        }
                                    )
                        elif condition_id:
                            # Используем conditionId если нет tokens
                            active_tokens.append(
                                {
                                    "question": question,
                                    "token_id": condition_id,
                                    "outcome": "N/A",
                                    "condition_id": condition_id,
                                    "market_id": market_id,
                                    "end_date": end_date_str,
                                }
                            )
            except Exception as e:
                # Пропускаем маркеты с неправильной датой
                continue

        print(f"Найдено {len(future_markets)} маркетов с будущей датой")
        print(f"Найдено {len(active_tokens)} токенов\n")

        print("АКТИВНЫЕ МАРКЕТЫ 2026 (первые 10):")
        print("-" * 70)

        for i, token_info in enumerate(active_tokens[:10], 1):
            question = token_info["question"]
            end_date = token_info["end_date"]
            token_id = token_info["token_id"]
            outcome = token_info["outcome"]

            print(f"\n{i}. {question[:60]}...")
            print(f"   Дата окончания: {end_date}")
            print(f"   Исход: {outcome}")
            print(
                f"   Token ID: {token_id[:50]}..."
                if len(token_id) > 50
                else f"   Token ID: {token_id}"
            )

        print("\n" + "=" * 70)
        print("\nГОТОВЫЕ ТОКЕНЫ ДЛЯ WebSocket:")
        print("-" * 70)

        if active_tokens:
            # Сохраняем в файл
            token_list = [t["token_id"] for t in active_tokens[:5]]

            print("\nPython код для использования:")
            print("\n```python")
            print("# Токены для WebSocket подписки (2026)")
            print(f"token_ids = {json.dumps(token_list, indent=4)}")
            print("\n# Использование:")
            print("await ws.subscribe_tokens(token_ids)")
            print("```")

            # Сохраняем в JSON файл
            with open("active_tokens_2026.json", "w", encoding="utf-8") as f:
                json.dump(active_tokens[:5], f, indent=2, ensure_ascii=False)

            print("\n✅ Токены сохранены в файл: active_tokens_2026.json")

            # Показываем первый токен для теста
            print(f"\n📝 Пример использования первого токена:")
            first = active_tokens[0]
            print(f"   Вопрос: {first['question'][:50]}...")
            print(f"   Дата окончания: {first['end_date']}")
            print(f"   Token ID: {first['token_id'][:60]}...")

        else:
            print("\n❌ Не найдено активных токенов на 2026 год")
            print("   Возможные причины:")
            print("   - Все маркеты в API устарели")
            print("   - Нужен API ключ для доступа к актуальным данным")
            print("   - Фильтр active_only работает некорректно")

        return active_tokens

    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()
        return []

    finally:
        await client.close()


if __name__ == "__main__":
    print(f"Получение актуальных токенов Polymarket")
    print(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()

    tokens = asyncio.run(get_active_tokens())

    print("\n" + "=" * 70)
    if tokens:
        print(f"✅ Готово! Найдено {len(tokens)} актуальных токенов 2026")
        print("   Используйте файл active_tokens_2026.json")
    else:
        print("❌ Актуальные токены не найдены")
        print("   API возвращает только старые маркеты 2020-2021")
    print("=" * 70)
