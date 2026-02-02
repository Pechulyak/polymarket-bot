# Polymarket Trading Bot — Architecture

## System Overview
High-frequency arbitrage bot exploiting structural inefficiencies across Polymarket and Bybit. No predictive models — pure statistical arbitrage, liquidity imbalances, and cross-exchange spreads.

**Initial Capital**: $10 (virtual bankroll → live trading)  
**Position Sizing**: Full Kelly Criterion  
**Risk Management**: Kill switch on ban detection or drawdown limits

---

## System Components

### 1. Data Ingestion Layer

**Purpose**: Real-time market data collection from multiple sources

**Modules**:
- `market_data_feed.py` — WebSocket connections to Polymarket & Bybit
- `orderbook_sync.py` — Order book depth synchronization
- `trade_aggregator.py` — Historical trade data collection
- `fee_tracker.py` — Real-time fee monitoring across all hops

**Data Flow**:
```
Polymarket API → WebSocket → Normalizer → PostgreSQL
Bybit API → WebSocket → Normalizer → PostgreSQL
Gas Station API → HTTP → Gas Oracle → PostgreSQL
```

### 2. Strategy Engine

**Purpose**: Detect and evaluate arbitrage opportunities

**Modules**:
- `cross_exchange_arbitrage.py` — Polymarket ↔ Bybit spread detection
- `liquidity_skew_detector.py` — Order book imbalance exploitation
- `behavioral_bias_scanner.py` — Market sentiment vs price divergences
- `kelly_calculator.py` — Position sizing based on edge and bankroll
- `opportunity_filter.py` — Filter by min spread (10 bps after fees)

**Strategy Types**:
1. **Cross-Exchange Arbitrage** — Same event, different prices
2. **Liquidity Skew** — Large orders creating temporary mispricings
3. **Settlement Arbitrage** — Pre-settlement price drift
4. **New Market Inefficiency** — Initial pricing errors on new markets

### 3. Execution Engine

**Purpose**: Order placement, lifecycle management, hedging

**Modules**:
- `polymarket_executor.py` — Polymarket order execution via CTFExchange
- `bybit_hedger.py` — Counter-position management on Bybit
- `wallet_manager.py` — MetaMask transaction signing & nonce management
- `gas_optimizer.py` — Dynamic gas price adjustment
- `order_lifecycle.py` — Track order status from creation to fill

**Execution Flow**:
```
Opportunity Detected → Kelly Sizing → Risk Check → 
Polymarket Buy + Bybit Sell → Confirm Fill → 
Update Positions → Log PnL
```

### 4. Risk Management System

**Purpose**: Capital preservation and compliance

**Modules**:
- `kill_switch.py` — Emergency stop with position unwinding
- `position_monitor.py` — Real-time exposure tracking
- `drawdown_calculator.py` — Daily/weekly loss monitoring
- `ban_detector.py` — Pattern analysis for account flagging
- `commission_tracker.py` — Fee accounting per trade leg

**Kill Switch Triggers**:
- Single trade drawdown > 5% of bankroll
- Daily loss > 2% of bankroll
- Failed execution > 3 times in 10 minutes
- API latency > 5 seconds
- Ban risk score > threshold
- Manual override

---

## PostgreSQL Schema

### Core Tables

```sql
-- Market data cache
CREATE TABLE market_data (
    id SERIAL PRIMARY KEY,
    market_id VARCHAR(255) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    best_bid DECIMAL(20, 8) NOT NULL,
    best_ask DECIMAL(20, 8) NOT NULL,
    bid_volume DECIMAL(20, 8),
    ask_volume DECIMAL(20, 8),
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    INDEX idx_market_time (market_id, timestamp)
);

-- Trading opportunities detected
CREATE TABLE opportunities (
    id SERIAL PRIMARY KEY,
    opportunity_id UUID UNIQUE NOT NULL,
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
    executed BOOLEAN DEFAULT FALSE,
    INDEX idx_detected (detected_at, executed)
);

-- Trade execution log
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    trade_id UUID UNIQUE NOT NULL,
    opportunity_id UUID REFERENCES opportunities(opportunity_id),
    market_id VARCHAR(255) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    size DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    
    -- Fee breakdown
    commission DECIMAL(20, 8) NOT NULL,
    gas_cost_eth DECIMAL(20, 18),
    gas_cost_usd DECIMAL(20, 8),
    fiat_fees DECIMAL(20, 8), -- Bybit deposit/withdrawal
    
    -- PnL tracking
    gross_pnl DECIMAL(20, 8),
    total_fees DECIMAL(20, 8),
    net_pnl DECIMAL(20, 8),
    
    status VARCHAR(50) NOT NULL,
    executed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    settled_at TIMESTAMP,
    
    INDEX idx_market (market_id, executed_at),
    INDEX idx_status (status)
);

-- Position tracking
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    position_id UUID UNIQUE NOT NULL,
    market_id VARCHAR(255) NOT NULL,
    polymarket_size DECIMAL(20, 8) NOT NULL DEFAULT 0,
    bybit_size DECIMAL(20, 8) NOT NULL DEFAULT 0,
    net_exposure DECIMAL(20, 8) NOT NULL DEFAULT 0,
    avg_entry_price DECIMAL(20, 8),
    unrealized_pnl DECIMAL(20, 8) DEFAULT 0,
    realized_pnl DECIMAL(20, 8) DEFAULT 0,
    opened_at TIMESTAMP NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    INDEX idx_market_status (market_id, status)
);

-- Bankroll tracking
CREATE TABLE bankroll (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    total_capital DECIMAL(20, 8) NOT NULL,
    allocated DECIMAL(20, 8) NOT NULL DEFAULT 0,
    available DECIMAL(20, 8) NOT NULL,
    daily_pnl DECIMAL(20, 8) DEFAULT 0,
    daily_drawdown DECIMAL(10, 4) DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    INDEX idx_timestamp (timestamp)
);

-- Risk events log
CREATE TABLE risk_events (
    id SERIAL PRIMARY KEY,
    event_id UUID UNIQUE NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    description TEXT NOT NULL,
    market_id VARCHAR(255),
    position_id UUID,
    triggered_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP,
    resolution_notes TEXT,
    INDEX idx_triggered (triggered_at, severity)
);

-- Fee structure (updated periodically)
CREATE TABLE fee_schedule (
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
CREATE TABLE api_health (
    id SERIAL PRIMARY KEY,
    exchange VARCHAR(50) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    latency_ms INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    checked_at TIMESTAMP NOT NULL DEFAULT NOW(),
    INDEX idx_checked (checked_at, exchange)
);
```

---

## API Integrations

### Polymarket API

**Client**: `polymarket_client.py`

**Endpoints**:
- `GET /markets` — List all markets
- `GET /markets/{id}/orderbook` — Order book depth
- `POST /orders` — Place order (signed transaction)
- `GET /orders/{id}` — Order status
- `WebSocket /ws/markets` — Real-time price feed

**Authentication**: MetaMask wallet signing (EIP-712)

**Rate Limits**: 
- 100 requests/minute REST
- 1 connection WebSocket

**Key Methods**:
```python
async def get_orderbook(self, market_id: str) -> OrderBook
async def place_order(self, order: PolymarketOrder) -> OrderResult
async def cancel_order(self, order_id: str) -> bool
async def get_positions(self) -> List[Position]
```

### Bybit API

**Client**: `bybit_client.py`

**Endpoints**:
- `GET /v5/market/orderbook` — Order book
- `POST /v5/order/create` — Place order
- `GET /v5/order/realtime` — Active orders
- `WebSocket /v5/public/linear` — Price feed

**Authentication**: API Key + HMAC-SHA256 signature

**Rate Limits**:
- 120 requests/second (API Key)
- 50 orders/second

**Key Methods**:
```python
async def get_orderbook(self, symbol: str) -> OrderBook
async def place_order(self, side: Side, size: Decimal) -> OrderResult
async def hedge_position(self, market_id: str, size: Decimal) -> HedgeResult
```

### MetaMask Integration

**Client**: `wallet_manager.py`

**Functions**:
- Transaction signing via Ethers.js bridge
- Nonce management
- Gas price optimization
- Multi-account support (rotation for ban avoidance)

**Key Methods**:
```python
async def sign_transaction(self, tx: dict) -> SignedTx
async def get_gas_price(self) -> int  # Gwei
async def estimate_gas(self, tx: dict) -> int
async def rotate_account(self) -> str  # New address
```

---

## Python Modules Structure

```
src/
├── __init__.py
├── config/
│   ├── __init__.py
│   ├── settings.py          # Environment-based config
│   ├── exchanges.py         # Exchange-specific settings
│   └── risk_params.py       # Risk limits & thresholds
│
├── data/
│   ├── __init__.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── polymarket_feed.py
│   │   ├── bybit_feed.py
│   │   └── gas_oracle.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── postgres_client.py
│   │   └── cache_manager.py
│   └── models/
│       ├── __init__.py
│       ├── market_data.py
│       ├── order.py
│       └── position.py
│
├── strategy/
│   ├── __init__.py
│   ├── arbitrage/
│   │   ├── __init__.py
│   │   ├── cross_exchange.py
│   │   ├── liquidity_skew.py
│   │   └── settlement.py
│   ├── kelly_criterion.py
│   ├── opportunity_filter.py
│   └── edge_calculator.py
│
├── execution/
│   ├── __init__.py
│   ├── polymarket/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── order_manager.py
│   │   └── position_tracker.py
│   ├── bybit/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   └── hedger.py
│   ├── wallet/
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   └── gas_optimizer.py
│   └── orchestrator.py      # Main execution loop
│
├── risk/
│   ├── __init__.py
│   ├── kill_switch.py
│   ├── position_limits.py
│   ├── drawdown_monitor.py
│   ├── ban_detector.py
│   └── commission_tracker.py
│
├── research/
│   ├── __init__.py
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── github.py
│   │   ├── twitter.py
│   │   ├── linkedin.py
│   │   ├── discord.py
│   │   └── reddit.py
│   └── signal_processor.py
│
├── monitoring/
│   ├── __init__.py
│   ├── logger.py
│   ├── metrics.py
│   └── alerts.py
│
└── main.py                  # Entry point
```

### Key Module Descriptions

**`strategy/kelly_criterion.py`**
- Implements Kelly formula: f* = (bp - q) / b
- Calculates optimal position size based on edge
- Returns 0 if edge ≤ 0
- Never exceeds 25% of bankroll (quarter Kelly for safety)

**`execution/orchestrator.py`**
- Main trading loop (async)
- Polls for opportunities every 100ms
- Coordinates execution across exchanges
- Handles partial fills and slippage

**`risk/kill_switch.py`**
- Monitors all risk triggers
- Cancels all orders on activation
- Unwinds positions if profitable
- Logs incident and sends alerts
- Prevents new trades until manual reset

**`risk/commission_tracker.py`**
- Tracks fees at every hop:
  - Fiat → Bybit (deposit fees)
  - Bybit trading fees
  - Withdrawal to MetaMask (gas)
  - Polymarket trading fees
- Calculates net edge after all costs

---

## Git Workflow

### Milestone Commits Only

All commits to main branch must be milestone commits with semantic versioning.

**Commit Format**:
```
milestone: <module> v<version> - <description>

- Feature 1
- Feature 2
- Bug fixes
```

**Examples**:
```bash
# Research phase complete
git commit -m "milestone: research v0.1.0 - strategy analysis framework

- GitHub scraper for repo analysis
- Twitter/X sentiment collector
- Reddit r/polymarket monitor
- Signal aggregation engine"

# Strategy engine ready
git commit -m "milestone: strategy v0.2.0 - arbitrage detection

- Cross-exchange spread calculator
- Kelly Criterion position sizing
- Liquidity skew detector
- 10 bps minimum edge filter"

# Execution live
git commit -m "milestone: execution v0.3.0 - live trading

- Polymarket API integration
- Bybit hedging implementation
- MetaMask wallet management
- Gas optimization"

# Risk management
git commit -m "milestone: risk v0.4.0 - kill switch & monitoring

- Emergency stop mechanism
- Position limit enforcement
- Drawdown monitoring
- Commission tracking"

# Production release
git commit -m "milestone: bot v1.0.0 - production ready

- Virtual bankroll testing complete
- $10 → $12.50 (25% ROI)
- 47 trades, 38 wins (81% win rate)
- Ready for live deployment"
```

### Tagging

```bash
# Tag on milestone commit
git tag -a v0.3.0 -m "Execution module complete"

# Push with tags
git push origin main --tags
```

### Branch Strategy

- `main` — Production-ready code (milestone commits only)
- `dev` — Integration branch for features
- `feat/<name>` — Feature branches (squash merge to dev)
- `fix/<name>` — Bug fixes (squash merge to dev)
- `research/<name>` — Strategy research (merge with full history)

---

## Deployment

### Development

```bash
# Start infrastructure
docker-compose -f docker/docker-compose.dev.yml up -d

# Run bot in paper mode
python src/main.py --mode paper --bankroll 10.00
```

### Production

```bash
# Deploy to production server
docker-compose -f docker/docker-compose.prod.yml up -d

# Run with live trading (after virtual bankroll validation)
python src/main.py --mode live --bankroll 10.00
```

### Environment Variables

```bash
# .env.production
POLYMARKET_API_KEY=xxx
BYBIT_API_KEY=xxx
BYBIT_SECRET=xxx
METAMASK_PRIVATE_KEY=xxx  # Encrypted
DATABASE_URL=postgresql://...
RISK_MAX_DRAWDOWN=0.02
RISK_KILL_SWITCH_ENABLED=true
TELEGRAM_ALERT_BOT_TOKEN=xxx
```

---

## Success Metrics

**Primary Goal**: Bankroll growth from $10

**Key Metrics**:
- Daily ROI
- Sharpe ratio (target > 1.5)
- Win rate vs Kelly predictions
- Average trade duration (< 1 hour target)
- Max drawdown (< 2% daily)
- Fee efficiency (net edge > 10 bps)

**Decision Matrix**:
- ROI < 0% after 100 trades → Return to research phase
- ROI > 0% but < 5% → Strategy refinement
- ROI > 5% → Scale position sizing
- ROI > 25% → Ready for live trading
