# Промт: Переход в Чат "Разработка"

## Использование

Скопируйте этот промт и заполните поля [в квадратных скобках].

---

```
[MASTER] → [РАЗРАБОТКА]

═══════════════════════════════════════════════════════════════

ЗАДАЧА: 
[Опишите конкретно что нужно сделать. Например:
- Реализовать CopyTradingEngine для копирования сделок китов
- Интегрировать Polymarket CLOB API
- Создать модуль для расчета Kelly Criterion
- Исправить баг в OrderExecutor
]

═══════════════════════════════════════════════════════════════

КОНТЕКСТ ПРОЕКТА:

Polymarket Trading Bot — high-frequency arbitrage trading bot 
для prediction markets с начальным капиталом $100.

Стратегии:
- Copy Trading (70% / $70) — копирование сделок китов
- Cross-Platform Arbitrage (25% / $25) — арбитраж между биржами
- Gas Reserve (5% / $5)

Технологии: Python 3.11+, Web3.py, aiohttp, PostgreSQL, Redis

═══════════════════════════════════════════════════════════════

ТРЕБОВАНИЯ:
[Перечислите конкретные требования]

Обязательные:
1. [требование 1]
2. [требование 2]
3. [требование 3]

Желательные:
- [желательное 1]
- [желательное 2]

═══════════════════════════════════════════════════════════════

ОГРАНИЧЕНИЯ И ПРАВИЛА:

❌ ЗАПРЕЩЕНО:
- ML/LLM модели для прогнозирования
- Hardcoded API keys или secrets
- Synchronous код где можно async
- Float для финансовых расчетов (использовать Decimal)

✅ ОБЯЗАТЕЛЬНО:
- Type hints для всех функций
- Kelly Criterion для position sizing
- Error handling с specific exceptions
- Structlog логирование
- Unit tests (минимум 80% coverage)
- Следовать AGENTS.md code style

⚠️ ВАЖНО:
- Комиссии: fiat→Bybit→MetaMask→Polymarket (учитывать все)
- Kill switch при 2% daily drawdown
- Макс 25% банкрола на сделку
- WebSocket > REST (75-3000x faster)
- Raw TX signing 5-10x faster than REST API

═══════════════════════════════════════════════════════════════

ФАЙЛЫ ДЛЯ ОЗНАКОМЛЕНИЯ:

[Выберите из списка ниже или укажите свои]

ОБЯЗАТЕЛЬНЫЕ:
- AGENTS.md (code standards)
- ARCHITECTURE.md (system design)
- docs/bot_development_kit/00_QUICK_START.md

РЕФЕРЕНСНЫЕ МОДУЛИ:
- docs/bot_development_kit/04_CODE_LIBRARY/copy_trading_engine.py
- docs/bot_development_kit/04_CODE_LIBRARY/polymarket_client.py
- docs/bot_development_kit/04_CODE_LIBRARY/order_executor.py
- docs/bot_development_kit/04_CODE_LIBRARY/risk_manager.py

КОНФИГУРАЦИЯ:
- src/config/settings.py
- src/config/risk_params.py
- src/strategy/selected_strategies.py

ТЕСТЫ:
- tests/unit/test_kelly.py (пример структуры)

═══════════════════════════════════════════════════════════════

ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:

[Опишите что должно быть создано]

Новые файлы:
- src/[module]/[file].py

Измененные файлы:
- src/[module]/__init__.py

Тесты:
- tests/unit/test_[module].py

CHANGELOG (будет добавлено в docs/changelogs/development.md):
### [YYYY-MM-DD] - [Task Name]
#### Added
- [файлы]
#### Changed
- [файлы]
#### Technical Details
- [детали]

═══════════════════════════════════════════════════════════════

ДОПОЛНИТЕЛЬНО:

ПРИОРИТЕТ: [high / medium / low]

СРОК: [если есть дедлайн]

ЗАВИСИМОСТИ ОТ ДРУГИХ МОДУЛЕЙ:
- [если нужно дождаться другой задачи]

ИЗВЕСТНЫЕ ПРОБЛЕМЫ:
- [если есть]

═══════════════════════════════════════════════════════════════
```

---

## Примеры готовых промтов

### Пример 1: Новый модуль

```
[MASTER] → [РАЗРАБОТКА]

ЗАДАЧА: Реализовать CopyTradingEngine для копирования сделок китов

КОНТЕКСТ ПРОЕКТА:
[... стандартный контекст ...]

ТРЕБОВАНИЯ:
1. Класс CopyTradingEngine с методом process_transaction()
2. Декодирование CLOB транзакций (Web3)
3. Расчет размера позиции: (whale_trade / whale_balance) * my_balance
4. Лимиты: мин $5, макс $20 на сделку
5. Интеграция с OrderExecutor для исполнения
6. Отслеживание открытых позиций
7. Автоматическое закрытие когда кит выходит
8. Логирование всех операций

ОГРАНИЧЕНИЯ И ПРАВИЛА:
❌ ЗАПРЕЩЕНО:
- ML для выбора китов
- Hardcoded whale addresses

✅ ОБЯЗАТЕЛЬНО:
- Type hints
- Proportional sizing через Kelly
- Error handling
- Tests

ФАЙЛЫ ДЛЯ ОЗНАКОМЛЕНИЯ:
- docs/bot_development_kit/04_CODE_LIBRARY/copy_trading_engine.py
- docs/bot_development_kit/01_COPY_TRADING_GUIDE.md
- AGENTS.md

ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:
Новые файлы:
- src/execution/copy_trading_engine.py

Тесты:
- tests/unit/test_copy_trading.py

ПРИОРИТЕТ: high
```

### Пример 2: Интеграция API

```
[MASTER] → [РАЗРАБОТКА]

ЗАДАЧА: Интегрировать Bybit API для хеджирования позиций

КОНТЕКСТ ПРОЕКТА:
[... стандартный контекст ...]

ТРЕБОВАНИЯ:
1. Класс BybitClient (async)
2. Методы: get_orderbook(), place_order(), get_balance()
3. WebSocket соединение для real-time data
4. Авторизация через API key + HMAC
5. Rate limiting (120 req/sec)
6. Обработка ошибок и reconnect

ОГРАНИЧЕНИЯ:
- Использовать aiohttp
- Все данные в Decimal
- Логировать все запросы

ФАЙЛЫ ДЛЯ ОЗНАКОМЛЕНИЯ:
- docs/bot_development_kit/04_CODE_LIBRARY/polymarket_client.py (как пример)
- src/execution/bybit/ (существующая структура)

ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:
Новые файлы:
- src/execution/bybit/client.py
- src/execution/bybit/hedger.py

ПРИОРИТЕТ: medium
```

### Пример 3: Багфикс

```
[MASTER] → [РАЗРАБОТКА]

ЗАДАЧА: Исправить расчет Kelly Criterion (сейчас возвращает 0 при edge=0)

КОНТЕКСТ ПРОЕКТА:
[... стандартный контекст ...]

ТРЕБОВАНИЯ:
1. Исправить формулу: f* = (bp - q) / b
2. Добавить проверку на edge ≤ 0 (return 0)
3. Добавить cap на 25% (quarter Kelly)
4. Написать тесты для edge cases

ТЕКУЩЕЕ ПОВЕДЕНИЕ:
- При win_rate=0.6, payoff=2.0 возвращает 0 (должно быть 0.4)

ОЖИДАЕМОЕ ПОВЕДЕНИЕ:
- Корректный расчет по формуле Kelly

ФАЙЛЫ ДЛЯ ОЗНАКОМЛЕНИЯ:
- src/strategy/kelly_criterion.py (если существует)
- tests/unit/test_kelly.py

ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:
Измененные файлы:
- src/strategy/kelly_criterion.py
- tests/unit/test_kelly.py

ПРИОРИТЕТ: high
```

---

## Проверка перед отправкой

- [ ] Задача описана конкретно и понятно
- [ ] Контекст заполнен
- [ ] Требования перечислены
- [ ] Ограничения указаны
- [ ] Файлы для ознакомления выбраны
- [ ] Ожидаемый результат определен
- [ ] Changelog формат указан
- [ ] Приоритет установлен

---

## ⚠️ ВАЖНО: Changelog Required

**При возврате отчета в Master Chat ОБЯЗАТЕЛЬНО включить:**

```
CHANGELOG (добавить в docs/changelogs/development.md):

### [YYYY-MM-DD] - [Task Name]
#### Added
- [конкретные файлы]
#### Changed
- [конкретные файлы]
#### Technical Details
- [implementation details]
#### Breaking Changes
- [none если нет]
```

**Без changelog milestone commit не будет создан!**

---

**После выполнения задачи Разработка отправит отчет обратно в Master Chat**
