# Polymarket Trading Bot — AGENTS.md

## Project Overview
High-frequency arbitrage trading bot for Polymarket prediction markets. Focuses on structural inefficiencies, cross-exchange arbitrage, and Kelly Criterion-based position sizing. No ML/LLM prediction models.

## Architecture

### Core Modules

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
master-chat/
  src/
    coordinator.py       # Milestone commit orchestration
    changelog.py         # Aggregates module changelogs
    git_manager.py       # GitHub milestone management

research/
  src/
    scrapers/
      github.py          # Strategy repos analysis
      twitter.py         # X sentiment & alpha
      linkedin.py        # Institutional signals
      discord.py         # Community alpha
      reddit.py          # r/wallstreetbets, r/polymarket
    aggregators/
      signal_processor.py # Normalize & weight signals

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

```sql
-- Trades table
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    trade_id UUID UNIQUE NOT NULL,
    market_id VARCHAR(255) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    size DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    commission DECIMAL(20, 8) NOT NULL,
    net_pnl DECIMAL(20, 8),
    executed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    strategy VARCHAR(100) NOT NULL
);

-- Risk events
CREATE TABLE risk_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    description TEXT NOT NULL,
    triggered_at TIMESTAMP NOT NULL DEFAULT NOW()
);
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
