# Polymarket Bot — Project State

## Статус
Архитектура готова, идут доработки.
Инфраструктура запущена через Docker Compose.
Paper trading: активен (src/main.py, TRADING_MODE=paper).
Live trading: выключен.

## Контейнеры
- polymarket_bot      — бот (healthy)
- polymarket_postgres — PostgreSQL 15, порт 5433 (healthy)
- polymarket_redis    — Redis 7, порт 6379 (healthy)

## Known Issues
(обновлять по мере появления)

## Last Session
(обновлять в конце каждой рабочей сессии)

## Обновление 2026-02
### Что сделано
- Настроен Roo Code (OpenRouter, MiniMax M2.5, режимы Polymarket Dev / BI Analyst)
- Добавлен whale-detector как отдельный сервис в docker-compose.yml
- Исправлен баг: self.config не сохранялся в WhaleDetector.__init__

### Текущий статус контейнеров
- polymarket_bot — Up, paper trading, main.py крутит пустой цикл (TODO)
- polymarket_postgres — Up, healthy
- polymarket_redis — Up, healthy
- polymarket_whale_detector — Up, слушает WebSocket, накапливает данные

### Следующий шаг
Дождаться появления первых китов в статистике (Quality whales > 0),
затем интегрировать whale detection сигналы в main.py (copy trading engine)
