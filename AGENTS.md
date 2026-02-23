# AI Agent Working Rules
> Этот блок — обязательные правила работы AI-агента. Приоритет выше всех остальных инструкций.

## Пошаговый рабочий процесс (ОБЯЗАТЕЛЬНО)
1. Прочитать все затрагиваемые файлы полностью
2. Изложить план (не более 5 шагов) — **ждать подтверждения**
3. Выполнить шаг 1 — отчитаться — **ждать подтверждения**
4. Выполнить шаг 2 — отчитаться — **ждать подтверждения**
5. И так далее — **НЕ переходить к следующему шагу без явного подтверждения**
6. Summary: что сделано, риски, что дальше

## Контекст окружения
- Сервер: Ubuntu 24.04, проект в ~/polymarket-bot/
- Инфраструктура: Docker Compose (postgres + redis + bot)
- Язык общения: русский, кратко и по делу
- Пользователь: ставит задачи и тестирует, код не пишет

## Docker команды (не systemd!)
docker compose ps                          # статус
docker compose logs -f bot                 # логи бота
docker compose restart bot                 # рестарт бота
docker compose down && docker compose up -d # полный перезапуск

## Требуют явного "подтверждаю":
- docker compose down
- docker compose restart bot
- изменение .env
- DROP TABLE / DELETE без WHERE
- TRADING_MODE=live — только после 7 дней paper без ошибок
- Перед началом задачи читать memory-bank/errors-log.md

---

# Polymarket Trading Bot — AGENTS.md

## Project Overview
High-frequency arbitrage trading bot for Polymarket prediction markets. Focuses on structural inefficiencies, cross-exchange arbitrage, and Kelly Criterion-based position sizing. No ML/LLM prediction models.

## Architecture

### Current Project Status (2026-02-20)

### Recent Changes
- Polymarket Data API: Free, real-time, includes trader addresses
- Builder API: Integrated for gasless transactions
- Whale Detection: Using PolymarketDataClient (no API key needed)
- Top whale found: $17,200 in single trade
- 34 unique traders detected in 37 trades

- **Master-Chat**: Central coordinator for milestone commits, aggregates changelog across modules
- **Research Module**: Strategy analysis via GitHub, Twitter/X, LinkedIn, Discord, Reddit scraping
- **Strategy Module**: Arbitrage detection, market inefficiencies, Kelly Criterion calculations
- **Execution Module**: Polymarket API integration, Bybit hedging, MetaMask wallet management
- **Risk Module**: Kill-switch mechanisms, commission tracking, position limits, drawdown controls

## Tech Stack

- **Language**: Python 3.11+ (primary) or Node.js 18+ (optional)
- **Database**: PostgreSQL (market data, trades, execution logs)
- **Containerization**: Docker, Docker Compose
- **Version Control**: GitHub with milestone-based commits
- **APIs**: Polymarket REST/WebSocket, Bybit API, Ethers.js for MetaMask

## Directory Structure

```
src/
  main.py                  # Main entry point
  main_paper_trading.py   # Paper trading runner
  run_whale_detection.py  # Whale detection runner

config/
  settings.py             # Configuration
  risk_params.py          # Risk parameters

research/
  polymarket_data_client.py  # Data API client
  whale_detector.py           # Whale detection
  whale_tracker.py            # Whale tracking
  real_time_whale_monitor.py # Real-time monitor

execution/
  copy_trading_engine.py     # Copy trading engine
  polymarket/
    client.py            # REST API client
    builder_client.py    # Builder API (gasless)

strategy/
  virtual_bankroll.py    # Virtual bankroll tracker
  selected_strategies.py # Strategy configs

data/
  ingestion/
    websocket_client.py  # WebSocket client

monitoring/
  logger.py             # Logging

scripts/
  init_db.sql           # Database schema
  test_infrastructure.py # Infra test
```
    whale_detector.py    # Real-time whale detection
    polymarket_data_client.py # Polymarket Data API client

strategy/
  src/
    arbitrage/
      cross_exchange.py  # Polymarket ↔ Bybit arb
      market_making.py   # Order book inefficiencies
    kelly_criterion.py   # Position sizing calculator
    inefficiency_scanner.py # Structural mispricings

execution/
  src/
    polymarket/
      api_client.py      # REST/WebSocket client
      order_manager.py   # Order lifecycle
    bybit/
      hedging.py         # Counter-position management
    wallet/
      metamask.py        # Transaction signing
      gas_optimizer.py   # Gas price management

risk/
  src/
    kill_switch.py       # Emergency stop mechanisms
    commission_tracker.py # Fee accounting per trade
    position_limits.py   # Max exposure controls
    drawdown_monitor.py  # Circuit breakers

database/
  migrations/            # PostgreSQL schema
  models/                # SQLAlchemy/Prisma models

docker/
  Dockerfile             # Multi-stage build
  docker-compose.yml     # Services orchestration
```

## Build Commands

### Python Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Development mode
pip install -e .

# Run all tests
pytest tests/ -v

# Run single test file
pytest tests/test_arbitrage.py -v

# Run single test
pytest tests/test_kelly.py::test_position_sizing -v

# Coverage report
pytest --cov=src --cov-report=html --cov-report=term

# Type checking
mypy src/ --ignore-missing-imports

# Linting
ruff check src/
ruff format src/

# Import sorting
isort src/ --profile black
```

### Database
```bash
# Start PostgreSQL
docker-compose up -d postgres

# Run migrations
alembic upgrade head

# Create migration
alembic revision --autogenerate -m "add_trades_table"
```

### Docker
```bash
# Build all services
docker-compose build

# Start trading bot
docker-compose up -d

# View logs
docker-compose logs -f execution

# Emergency stop
docker-compose down
```

### GitHub Milestones
```bash
# Create milestone commit
git commit -m "milestone: arbitrage engine v1.2"

# Tag release
git tag -a v1.2.0 -m "Kelly Criterion integration"
```

## Code Style Guidelines

### Python

**Imports:**
```python
# Standard library
import os
from datetime import datetime
from decimal import Decimal
from typing import Optional

# Third-party
import aiohttp
import pandas as pd
from pydantic import BaseModel
from sqlalchemy import Column, Integer

# Local modules
from execution.polymarket import PolymarketClient
from risk.kill_switch import EmergencyStop
```

**Formatting:**
- Line length: 100 characters
- Black formatter with default settings
- Trailing commas in multi-line structures

**Types:**
- All functions must have type hints
- Use `Decimal` for financial calculations (never float)
- Pydantic models for API responses

```python
class ArbitrageOpportunity(BaseModel):
    market_id: str
    polymarket_price: Decimal
    bybit_price: Decimal
    spread_bps: Decimal
    max_size: Decimal

async def calculate_kelly_position(
    bankroll: Decimal,
    win_probability: Decimal,
    payoff_ratio: Decimal
) -> Decimal:
    """Kelly Criterion: f* = (bp - q) / b"""
    b = payoff_ratio
    p = win_probability
    q = Decimal('1') - p
    kelly_fraction = (b * p - q) / b
    return bankroll * max(kelly_fraction, Decimal('0'))
```

**Naming:**
- `snake_case` for functions, variables
- `PascalCase` for classes
- `SCREAMING_SNAKE_CASE` for constants
- Prefix private methods with `_`

**Error Handling:**
```python
class ExecutionError(Exception):
    pass

class RiskLimitExceeded(Exception):
    pass

async def execute_arbitrage(self, opp: ArbitrageOpportunity) -> None:
    try:
        # Check risk limits first
        if not self.risk_module.can_trade(opp.max_size):
            raise RiskLimitExceeded(f"Position limit exceeded: {opp.max_size}")
        
        # Execute trades
        await self._execute_polymarket_buy(opp)
        await self._execute_bybit_sell(opp)
        
    except RiskLimitExceeded:
        self.kill_switch.activate("Position limit breached")
        raise
    except Exception as e:
        logger.error(f"Arbitrage failed: {e}", extra={"opportunity": opp.dict()})
        await self._emergency_unwind()
        raise ExecutionError(f"Trade execution failed: {e}") from e
```

### Database Schema

#### Connection Details
```env
# PostgreSQL Connection (development)
DATABASE_URL=postgresql://postgres:password@localhost:5433/postgres

# Docker PostgreSQL
# Host: localhost, Port: 5433, User: postgres, Password: password, Database: postgres
```

#### Schema (init_db.sql)

```sql
-- Market data cache
CREATE TABLE IF NOT EXISTS market_data (
    id SERIAL PRIMARY KEY,
    market_id VARCHAR(255) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    best_bid DECIMAL(20, 8) NOT NULL,
    best_ask DECIMAL(20, 8) NOT NULL,
    bid_volume DECIMAL(20, 8),
    ask_volume DECIMAL(20, 8),
    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Trading opportunities detected
CREATE TABLE IF NOT EXISTS opportunities (
    id SERIAL PRIMARY KEY,
    opportunity_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    market_id VARCHAR(255) NOT NULL,
    strategy VARCHAR(100) NOT NULL,
    polymarket_price DECIMAL(20, 8) NOT NULL,
    bybit_price DECIMAL(20, 8) NOT NULL,
    spread_bps DECIMAL(10, 4) NOT NULL,
    gross_edge DECIMAL(20, 8) NOT NULL,
    net_edge DECIMAL(20, 8) NOT NULL,
    kelly_fraction DECIMAL(10, 8) NOT NULL,
    recommended_size DECIMAL(20, 8) NOT NULL,
    detected_at TIMESTAMP NOT NULL DEFAULT NOW(),
    executed BOOLEAN DEFAULT FALSE
);

-- Trade execution log
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    trade_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    opportunity_id UUID REFERENCES opportunities(opportunity_id),
    market_id VARCHAR(255) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    size DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    commission DECIMAL(20, 8) NOT NULL,
    gas_cost_eth DECIMAL(20, 18),
    gas_cost_usd DECIMAL(20, 8),
    fiat_fees DECIMAL(20, 8),
    gross_pnl DECIMAL(20, 8),
    total_fees DECIMAL(20, 8),
    net_pnl DECIMAL(20, 8),
    status VARCHAR(50) NOT NULL,
    executed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    settled_at TIMESTAMP
);

-- Position tracking
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    position_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    market_id VARCHAR(255) NOT NULL,
    polymarket_size DECIMAL(20, 8) NOT NULL DEFAULT 0,
    bybit_size DECIMAL(20, 8) NOT NULL DEFAULT 0,
    net_exposure DECIMAL(20, 8) NOT NULL DEFAULT 0,
    avg_entry_price DECIMAL(20, 8),
    unrealized_pnl DECIMAL(20, 8) DEFAULT 0,
    realized_pnl DECIMAL(20, 8) DEFAULT 0,
    opened_at TIMESTAMP NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'open'
);

-- Bankroll tracking (virtual and real)
CREATE TABLE IF NOT EXISTS bankroll (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    total_capital DECIMAL(20, 8) NOT NULL,
    allocated DECIMAL(20, 8) NOT NULL DEFAULT 0,
    available DECIMAL(20, 8) NOT NULL,
    daily_pnl DECIMAL(20, 8) DEFAULT 0,
    daily_drawdown DECIMAL(10, 4) DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0
);

-- Risk events log
CREATE TABLE IF NOT EXISTS risk_events (
    id SERIAL PRIMARY KEY,
    event_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    description TEXT NOT NULL,
    market_id VARCHAR(255),
    position_id UUID,
    triggered_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP,
    resolution_notes TEXT
);

-- Fee structure
CREATE TABLE IF NOT EXISTS fee_schedule (
    id SERIAL PRIMARY KEY,
    exchange VARCHAR(50) NOT NULL,
    fee_type VARCHAR(50) NOT NULL,
    fee_percentage DECIMAL(10, 6),
    fixed_fee DECIMAL(20, 8),
    currency VARCHAR(10),
    effective_from TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (exchange, fee_type, effective_from)
);

-- API latency monitoring
CREATE TABLE IF NOT EXISTS api_health (
    id SERIAL PRIMARY KEY,
    exchange VARCHAR(50) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    latency_ms INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    checked_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### Initialize Database
```bash
# Run schema
psql -U postgres -d postgres -f scripts/init_db.sql

# Or via Docker
docker exec -i polymarket-postgres-1 psql -U postgres -d postgres < scripts/init_db.sql
```

#### Virtual Trades Note
Virtual trades (paper trading) use the same `trades` table with `exchange='VIRTUAL'` and `status='open'/'closed'`.
```

## Constraints & Rules

### Strictly Prohibited
- ❌ Machine Learning models for price prediction
- ❌ LLM-based trading decisions
- ❌ Sentiment-based directional bets
- ❌ Technical analysis indicators (RSI, MACD, etc.)

### Allowed Strategies
- ✅ Cross-exchange arbitrage (Polymarket ↔ Bybit)
- ✅ Order book inefficiency exploitation
- ✅ Statistical arbitrage (mean reversion)
- ✅ Kelly Criterion position sizing
- ✅ Liquidity provision with edge

## Risk Management

### Kill Switch Triggers
1. Drawdown > 5% of bankroll (single trade)
2. Daily loss > 2% of bankroll
3. Failed trade execution > 3 times in 10 minutes
4. API latency > 5 seconds
5. Manual override signal

### Position Limits
- Max single trade: 2% of bankroll
- Max exposure per market: 5% of bankroll
- Max concurrent trades: 10
- Min profit threshold: 10 bps after fees

### Fee Accounting
- Track all commissions per trade
- Include gas costs for blockchain txs
- Net PnL = Gross PnL - Commissions - Gas

## Testing

### Unit Tests
```bash
# Test Kelly calculations
pytest tests/strategy/test_kelly.py -v

# Test risk limits
pytest tests/risk/test_position_limits.py -v

# Test arbitrage detection
pytest tests/strategy/test_arbitrage.py::test_spread_calculation -v
```

### Integration Tests
```bash
# Test with paper trading
pytest tests/integration/ --use-testnet -v

# Database migrations test
pytest tests/database/ -v
```

## Paper Trading / Virtual Bankroll (ОБЯЗАТЕЛЬНО)

**Перед live trading ОБЯЗАТЕЛЬНО минимум 7 дней (168 часов) paper trading:**

### Virtual Bankroll Mode
```bash
# Run with virtual bankroll (no real trades executed)
python src/main.py --mode paper --bankroll 100.00
```

### Что должен делать paper trading:
- ✅ Отслеживать реальные сделки китов (whale transactions)
- ✅ Рассчитывать virtual positions (как если бы мы копировали)
- ✅ Учитывать все fees (trading fees, gas costs)
- ✅ Трекать Win/Loss в virtual bankroll
- ✅ Сохранять в PostgreSQL для анализа
- ❌ НЕ исполнять реальные trades

### Критерии перехода к Live Trading (минимум 7 дней):
- [ ] 7+ дней paper trading без ошибок (168+ часов)
- [ ] Virtual bankroll > $125 (25% ROI target) - т.е. +$25 прибыли
- [ ] Win rate > 60%
- [ ] No consecutive losses > 3
- [ ] All fees correctly accounted
- [ ] Logs clean (no errors)
- [ ] Стабильная работа без перебоев

### Тестирование:
```bash
# Run paper trading (минимум 7 дней)
python src/main.py --mode paper --bankroll 100.00 --duration 7d

# Check results daily
psql -c "SELECT DATE(executed_at) as day, COUNT(*) as trades, SUM(net_pnl) as pnl FROM virtual_trades GROUP BY DATE(executed_at) ORDER BY day;"
```

## Git Workflow

### Milestone Commits
- Use `milestone:` prefix for significant features
- Tag releases with semantic versioning
- Update CHANGELOG.md with each milestone

```bash
git commit -m "milestone: cross-exchange arbitrage v2.0"
git tag -a v2.0.0 -m "Bybit integration complete"
```

### Branch Naming
- `feat/arbitrage-engine`
- `fix/kelly-calculation`
- `risk/kill-switch-enhancement`

## Security

- Store API keys in environment variables only
- Use `.env` file (gitignored) for local dev
- Encrypt sensitive data in PostgreSQL
- Never log private keys or API secrets
- Use read-only API keys where possible
- Implement IP whitelisting for exchanges

## Monitoring

### Logs
- Structured JSON logging
- Log all trades with execution context
- Log risk events with severity levels

### Metrics
- Track Sharpe ratio daily
- Monitor win rate vs Kelly predictions
- Alert on kill switch activations

## Emergency Procedures

1. **Kill Switch Activation**
   - Cancel all pending orders
   - Close open positions (if profitable)
   - Send alert to Telegram/Discord
   - Log incident to risk_events table

2. **API Outage**
   - Pause trading for affected exchange
   - Hedge existing positions on other exchange
   - Monitor for recovery
