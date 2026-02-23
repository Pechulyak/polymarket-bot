## Project: Polymarket Following Bot
Python asyncio бот копирующий сделки китов на Polymarket.
Server: Ubuntu 24.04, ~/polymarket-bot/
Инфраструктура: Docker Compose (postgres + redis + bot).

## Stack
- Python 3.11, asyncio, SQLAlchemy 2.0, aiohttp, websockets
- PostgreSQL port=5433 (docker: 5433→5432)
- Redis port=6379
- web3, structlog, prometheus-client, sentry-sdk

## Entry Points
- src/main.py                 — live trading
- src/main_paper_trading.py   — paper trading (текущий режим)
- src/run_whale_detection.py  — whale detector

## Docker Commands
cd ~/polymarket-bot
docker compose ps                        # статус контейнеров
docker compose logs -f bot               # логи бота
docker compose logs -f                   # все логи
docker compose restart bot               # рестарт бота
docker compose down && docker compose up -d  # полный перезапуск

## Structure
src/config/     — settings, risk_params
src/research/   — whale_detector, data_client, tracker
src/execution/  — copy_trading_engine, builder_client
src/strategy/   — virtual_bankroll
src/data/       — websocket_client
src/monitoring/ — logger
src/risk/       — risk management
scripts/        — init_db.sql, test_infrastructure.py

## Ошибки и решения
Перед любой задачей читай memory-bank/errors-log.md — там зафиксированы прошлые ошибки которые нельзя повторять.
