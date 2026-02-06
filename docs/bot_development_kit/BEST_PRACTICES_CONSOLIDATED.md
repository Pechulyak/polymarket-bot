# Best Practices - Polymarket Arbitrage Bots
*Consolidated from 9 Level 2 analyses*

**Document Version:** 1.0
**Last Updated:** 2026-02-03
**Author:** AI Research Analyst

---

## Executive Summary

### Total Repositories Analyzed: 9

| Repository | Strategy Type | Language | $100 Viability | Best For |
|------------|--------------|----------|----------------|----------|
| apemoonspin/polymarket-arbitrage-trading-bot | Bundle (Orderbook Parity) | Python | 2/10 | Learning fee calculations |
| realfishsam/prediction-market-arbitrage-bot | Cross-Platform (Poly+Manifold) | Python | 8/10 | Foundation for $100 bot |
| CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot | Cross-Platform (Poly+Kalshi) | Python | 2/10 | Learning exchange abstraction |
| crypmancer/polymarket-arbitrage-copy-bot | Copy Trading (Whale Following) | Python | 8/10 | Beginner-friendly approach |
| cakaroni/polymarket-arbitrage-bot-btc-eth-15m | Time-Window Scalping | Python | 3/10 | Spot price oracles |
| hodlwarden/polymarket-arbitrage-copy-bot | Advanced Copy Trading | Python | 8/10 | Production deployment |
| 0xRustElite1111/polymarket-arbitrage-trading-bot | HFT Engine | Rust | 2/10 | Reference architecture |
| Jonmaa/btc-polymarket-bot | Technical Analysis | Python | 5/10 | Indicator modules |
| coleschaffer/Gabagool | Cross-Platform + Dashboard | TypeScript | 6/10 | UI/UX patterns |

### Key Finding Highlights

1. **Copy Trading is the most viable strategy for $100 capital** - Follow whales instead of competing with them
2. **3.15% Polymarket fee kills pure bundle arbitrage** - Post-fee era requires new approaches
3. **WebSocket beats REST by 75-3000x** - Critical for competitive latency
4. **Raw transaction signing is 5-10x faster than REST API** - Use `eth_account` directly
5. **Manifold is the best cross-platform partner** - No KYC, simpler API than Kalshi

### Recommended Approach for $100 Bot

**Primary Strategy:** Copy Trading (crypmancer or hodlwarden)
- No need to "outsmart" the market
- Follow profitable addresses
- Capital works only when there's a signal
- 5-20 opportunities per active day

**Secondary Strategy:** Cross-Platform Arbitrage (Polymarket + Manifold)
- Use realfishsam's architecture
- WebSocket for real-time data
- Lower competition than intra-platform

---

## 1. Arbitrage Detection Strategies

### Bundle Arbitrage (YES + NO ≠ $1.00)

**Best Implementations:**
- **apemoonspin**: Fee-aware detection with 3.15% accounting
- **realfishsam**: Price alignment logic between platforms

**Critical Patterns:**

```python
def detect_arbitrage_with_fees(yes_price, no_price, min_profit=0.01):
    """
    Post-3.15% Fee Era Implementation
    Source: apemoonspin/polymarket-arbitrage-trading-bot
    """
    total_cost = yes_price + no_price
    settlement_value = 1.0
    gross_profit = settlement_value - total_cost

    # Polymarket winner fee (3.15% of settlement value)
    platform_fee = settlement_value * 0.0315
    net_profit = gross_profit - platform_fee

    is_arbitrage = net_profit > min_profit
    return is_arbitrage, net_profit
```

**Minimum Viable Margin:** 5%+ (after 3.15% fee)

**Pitfalls to Avoid:**
- Trading when `yes + no < 0.99` without accounting for fees (loses money)
- Ignoring gas costs on small trades ($5-10 trades often unprofitable)
- Sequential order execution without slippage protection

### Cross-Platform Arbitrage

**Best Implementations:**
- **realfishsam**: Polymarket + Manifold (recommended for $100)
- **CarlosIbCu**: Polymarket + Kalshi (requires $500+ due to Kalshi minimums)
- **Gabagool**: Full-stack TypeScript with UI

**Critical Patterns:**

```python
# Unified Exchange Interface (from CarlosIbCu)
from abc import ABC, abstractmethod

class ExchangeInterface(ABC):
    @abstractmethod
    async def get_market_price(self, market_id: str) -> float:
        pass

    @abstractmethod
    async def place_order(self, market_id: str, side: str, amount: float, price: float) -> dict:
        pass

# Arbitrage Scanner (concurrent price fetching)
async def check_pair(poly_id, manifold_id):
    poly_price, manifold_price = await asyncio.gather(
        poly_client.get_market_price(poly_id),
        manifold_client.get_market_price(manifold_id)
    )
    spread = abs(poly_price - manifold_price)
    if spread > 0.05:  # 5% threshold
        return {'is_arb': True, 'spread': spread}
    return {'is_arb': False}
```

**Platform Comparison:**

| Platform | Min Capital | Latency | KYC | Best For |
|----------|-------------|---------|-----|----------|
| Manifold | $5 | 100ms | No | Beginners |
| Kalshi | $100+ | 200-500ms | Yes (US) | TradFi crossover |
| Polymarket | $10 | 50-100ms | No | Primary platform |

**Pitfalls to Avoid:**
- Splitting $100 between Kalshi + Poly (Kalshi deposits lock up capital)
- Manual market ID mapping (prone to errors)
- Ignoring "legging risk" when one side fails

### Statistical Arbitrage / Whale Copying

**Best Implementations:**
- **hodlwarden**: Raw TX signing, MEV protection (advanced)
- **crypmancer**: Block following, ABI decoding (beginner-friendly)

**Critical Patterns:**

```python
# Whale Transaction Decoder (from crypmancer)
from web3 import Web3

def decode_polymarket_trade(tx_input, abi):
    """Decodes CLOB trade transaction input"""
    w3 = Web3()
    try:
        decoded = w3.eth.contract(abi=abi).decode_function_input(tx_input)
        return {
            'action': decoded[0].fn_name,
            'market': decoded[1].get('token_id'),
            'amount': decoded[1].get('amount'),
            'price': decoded[1].get('price')
        }
    except Exception:
        return None

# Mempool Monitor (from hodlwarden)
async def monitor_pending_txs(rpc_url, target_address, callback):
    w3 = Web3(Web3.WebsocketProvider(rpc_url))
    tx_filter = w3.eth.filter('pending')

    while True:
        for tx_hash in tx_filter.get_new_entries():
            tx = w3.eth.get_transaction(tx_hash)
            if tx and tx['from'].lower() == target_address.lower():
                if tx.to == POLY_CLOB_ADDR:
                    await callback(tx)
        await asyncio.sleep(0.01)
```

**Whale Discovery Methods:**
1. Dune Analytics - Public Polymarket dashboards
2. Polygonscan - Filter by contract interactions
3. Polymarket Leaderboard - Top trader addresses

**Pitfalls to Avoid:**
- Copying "close" signals thinking they're "open" (entering opposite direction)
- Front-running without adequate gas (losing to whale's priority)
- Copying whales trading $1M+ (liquidity exhausted before your fill)

---

## 2. Architecture Patterns

### Real-Time Monitoring

**WebSocket vs Polling:**

| Method | Latency | Use Case | Implementation |
|--------|---------|----------|----------------|
| WebSocket | 5-100ms | Production, HFT | hodlwarden, realfishsam |
| REST Polling | 3000-15000ms | Research, backtesting | apemoonspin |

**WebSocket Wins:** Every production bot (7/9 analyzed) uses WebSocket

**Best Implementation:** hodlwarden + realfishsam combined approach

```python
# WebSocket Feed Handler (from realfishsam)
import asyncio
import websockets
import json

async def listen_polymarket_clob(on_message_callback):
    uri = "wss://clob.polymarket.com/ws"
    async with websockets.connect(uri) as websocket:
        subscribe_msg = {
            "type": "subscribe",
            "channel": "order_book",
            "id": "MARKET_ID"
        }
        await websocket.send(json.dumps(subscribe_msg))

        async for message in websocket:
            data = json.loads(message)
            await on_message_callback(data)
```

**Polling Acceptable For:**
- Initial research and backtesting
- Markets with low velocity (daily/weekly resolution)
- Fallback when WebSocket disconnects

### State Management

**In-Memory vs Database:**

| Approach | Speed | Persistence | Use Case |
|----------|-------|-------------|----------|
| In-Memory (Dict/Map) | Fastest | None | Active trading |
| SQLite | Fast | Local file | Research + trading |
| PostgreSQL | Medium | Full persistence | Production at scale |

**Recommended:** SQLite for $100 capital (simple + persistent)

```python
# Data Logger (from apemoonspin)
class ArbitrageDataLogger:
    def __init__(self, db_path="arbitrage.db"):
        self.conn = sqlite3.connect(db_path)
        self.init_database()

    def init_database(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                market_id TEXT,
                yes_price REAL,
                no_price REAL,
                net_profit REAL,
                executed BOOLEAN
            )
        ''')
        self.conn.commit()

    def log_opportunity(self, market_id, yes_price, no_price, executed=False):
        # Log for backtesting and performance analysis
        pass
```

### Order Execution Patterns

**Sequential vs Parallel:**

```python
# WRONG: Sequential (high slippage risk)
yes_order = await buy_yes(price)
no_order = await buy_no(price)  # Price may have moved!

# BETTER: Parallel submission
yes_order, no_order = await asyncio.gather(
    buy_yes(price),
    buy_no(price)
)

# BEST: Raw transaction with priority fee (hodlwarden)
# Build both transactions locally, submit with high gas
```

**Raw Transaction Signing (hodlwarden pattern):**

```python
def construct_raw_tx(market_id, side, price, amount, gas_price, nonce):
    contract = w3.eth.contract(address=EXCHANGE_ADDR, abi=ABI)

    transaction = contract.functions.createOrder(
        token_id=market_id,
        side=side,
        order_args=encode_order_args(price, amount)
    ).build_transaction({
        'chainId': 137,  # Polygon
        'gas': 300000,
        'maxFeePerGas': w3.to_wei(gas_price * 1.2, 'gwei'),
        'maxPriorityFeePerGas': w3.to_wei(gas_price * 1.5, 'gwei'),
        'nonce': nonce
    })

    signed_tx = w3.eth.account.sign_transaction(transaction, PRIVATE_KEY)
    return w3.eth.send_raw_transaction(signed_tx.rawTransaction)
```

---

## 3. Code Modules - Ready to Use

### Polymarket API Wrapper

**Winner:** realfishsam/prediction-market-arbitrage-bot
**Why:** Clean async WebSocket implementation, proper signing

```python
# Key components to extract:
# 1. WebSocket connection handler
# 2. EIP-712 order signing
# 3. Orderbook state manager
```

### Bundle Detection Algorithm

**Winner:** apemoonspin (for fee calculation)
**Location:** Embedded in analysis above
**Why:** Properly accounts for 3.15% platform fee

### Position Sizing

**Winner:** crypmancer (conviction-based sizing)

```python
def calculate_copy_size(whale_amount, whale_balance, my_balance):
    """
    Proportional sizing based on whale's conviction
    """
    conviction_ratio = whale_amount / whale_balance
    my_trade_size = my_balance * conviction_ratio

    # Apply caps
    if my_trade_size < MIN_TRADE_SIZE: return 0
    if my_trade_size > MAX_TRADE_SIZE: return MAX_TRADE_SIZE

    return my_trade_size
```

### Risk Manager

**Winner:** hodlwarden (gas-aware + position limits)

```python
class RiskManager:
    def __init__(self, max_position=15, max_daily_loss=10, max_gas_gwei=30):
        self.max_position_per_market = max_position
        self.daily_loss_limit = max_daily_loss
        self.max_gas_price = max_gas_gwei
        self.current_pnl = 0
        self.positions = {}

    def can_trade(self, market_id, size, current_gas_gwei):
        # Check daily loss limit
        if self.current_pnl < -self.daily_loss_limit:
            return False, "Daily loss limit hit"

        # Check position limits
        current_pos = self.positions.get(market_id, 0)
        if current_pos + size > self.max_position_per_market:
            return False, "Position limit exceeded"

        # Check gas sanity
        if current_gas_gwei > self.max_gas_price:
            return False, "Gas too expensive"

        return True, "OK"
```

### Gas Optimizer

**Winner:** hodlwarden (EIP-1559 aware)

```python
def get_eip1559_fees(w3, priority_level="medium"):
    """
    Calculate optimal gas fees for Polygon
    priority_level: low, medium, high
    """
    latest_block = w3.eth.get_block('latest')
    base_fee = latest_block['baseFeePerGas']

    priority_fees = {"low": 0.5, "medium": 1, "high": 2}
    priority_fee = w3.to_wei(priority_fees[priority_level], 'gwei')

    max_fee_per_gas = (base_fee * 2) + priority_fee

    return {
        "maxFeePerGas": max_fee_per_gas,
        "maxPriorityFeePerGas": priority_fee
    }

def estimate_polygon_gas_cost(w3, polygon_price_usd=0.50):
    """
    Estimate transaction cost in USD
    """
    gas_price_wei = w3.eth.gas_price
    gas_limit = 200000 * 2  # Two orders

    total_cost_matic = w3.from_wei(gas_price_wei * gas_limit, 'ether')
    total_cost_usd = float(total_cost_matic) * polygon_price_usd

    return total_cost_usd  # Typical: $0.001-0.01
```

### Spot Price Oracle

**Winner:** cakaroni (Binance WebSocket)

```python
class BinanceSpotStreamer:
    """Ultra-fast spot price for BTC/ETH markets"""

    def __init__(self, symbol="btcusdt"):
        self.symbol = symbol.lower()
        self.uri = "wss://stream.binance.com:9443/ws"
        self.callback = None

    async def start(self):
        async with websockets.connect(self.uri) as ws:
            await ws.send(json.dumps({
                "method": "SUBSCRIBE",
                "params": [f"{self.symbol}@trade"],
                "id": 1
            }))

            async for msg in ws:
                data = json.loads(msg)
                if 'p' in data:
                    price = float(data['p'])
                    if self.callback:
                        await self.callback(price)
```

---

## 4. Performance Benchmarks

| Metric | Best | Average | Worst | Best Source |
|--------|------|---------|-------|-------------|
| Detection Latency | 0.1ms (Rust) | 50-100ms (Python WS) | 15000ms (REST) | 0xRustElite1111 |
| Execution Speed | 60ms (raw tx) | 200-500ms (API) | 16s (sequential) | hodlwarden |
| Daily Opportunities | 50+ (copy trading) | 5-10 (cross-platform) | 0-2 (niche 15m) | crypmancer |
| Win Rate (copy) | 70%+ | 50-60% | 30% | hodlwarden |
| Gas per Trade | $0.001 | $0.01-0.05 | $0.15 | Polygon baseline |

### Latency Breakdown by Component

```
Component               Best Case    Typical
─────────────────────────────────────────────
Network receive         20ms         50-100ms
JSON parsing            0.1ms        2-5ms
Strategy calculation    0.05ms       1-10ms
Transaction signing     0.5ms        5-20ms
Network broadcast       20ms         50-100ms
Block confirmation      2000ms       2000-5000ms
─────────────────────────────────────────────
Total (excl. confirm)   40.65ms      ~200ms
```

---

## 5. $100 Capital Strategies

### Viable Approaches

#### 1. Copy Trading (Recommended)

- **Min Capital:** $50
- **Expected Daily Return:** $0.50-2.00 (0.5-2%)
- **Risk Level:** Medium (dependent on whale quality)
- **Best Implementation:** crypmancer (beginner) or hodlwarden (advanced)

**Setup Requirements:**
- Polygon RPC (Alchemy free tier OK for start)
- 3-5 curated whale addresses
- $50-100 USDC on Polymarket

**Daily Workflow:**
1. Bot monitors mempool/blocks for whale transactions
2. Decode trade intent (market, side, size)
3. Copy with proportional sizing
4. Exit when whale exits (or on profit target)

#### 2. Cross-Platform (Poly + Manifold) - Advanced

- **Min Capital:** $80 ($40 each side)
- **Expected Daily Return:** $0.20-1.00
- **Risk Level:** Medium-High (legging risk)
- **Best Implementation:** realfishsam

**Setup Requirements:**
- Both platform accounts funded
- Market ID mapping (manual)
- WebSocket feeds for both

#### 3. Bundle Arbitrage - Not Recommended

- **Min Capital:** $200+ (to overcome fees)
- **Expected Daily Return:** Negative post-fees
- **Risk Level:** High (deprecated strategy)
- **Reason:** 3.15% platform fee kills profitability

### Capital Efficiency Patterns

1. **Don't Split Too Thin:**
   - $100 on one platform > $50 on two platforms
   - Cross-platform requires $200+ minimum

2. **Compound Winnings:**
   - Reinvest profits immediately
   - $100 @ 1% daily = $137 after 30 days

3. **Use Limit Orders:**
   - Avoid market order slippage
   - Set price slightly better than best bid/ask

4. **Size Based on Opportunity Quality:**
   - 10% of capital for normal signals
   - 25% of capital for high-conviction (multiple whale agreement)

### Position Sizing for $100

```python
def calculate_position_size(balance, signal_strength, max_per_trade=0.25):
    """
    Conservative sizing for small accounts
    """
    base_size = balance * 0.10  # 10% base

    if signal_strength == "HIGH":
        return min(balance * max_per_trade, base_size * 2.5)
    elif signal_strength == "MEDIUM":
        return base_size * 1.5
    else:
        return base_size

# Example: $100 balance
# MEDIUM signal -> $15 position
# HIGH signal -> $25 position
```

---

## 6. Risk Management Essentials

### Kill Switch Patterns

**Best Implementation:** hodlwarden

```python
class KillSwitch:
    def __init__(self, max_daily_loss=10, max_consecutive_losses=3):
        self.max_daily_loss = max_daily_loss
        self.max_consecutive_losses = max_consecutive_losses
        self.daily_pnl = 0
        self.consecutive_losses = 0
        self.is_active = True

    def record_trade(self, pnl):
        self.daily_pnl += pnl

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # Check conditions
        if self.daily_pnl < -self.max_daily_loss:
            self.trigger("Daily loss limit exceeded")

        if self.consecutive_losses >= self.max_consecutive_losses:
            self.trigger("Consecutive losses exceeded")

    def trigger(self, reason):
        self.is_active = False
        # Close all positions
        # Send alert (Telegram/Email)
        print(f"KILL SWITCH: {reason}")
```

### Position Limits

**Recommended for $100 Capital:**
- Max position per market: $20 (20%)
- Max total exposure: $80 (80%)
- Cash reserve: $20 (20%) always

### Gas Cost Management (Polygon)

```python
def is_trade_profitable_after_gas(gross_profit_usd, trade_size, current_gas_gwei):
    """
    Check if trade is worth executing after gas costs
    """
    # Estimate gas cost
    gas_limit = 200000
    gas_cost_matic = (gas_limit * current_gas_gwei) / 1e9
    gas_cost_usd = gas_cost_matic * 0.50  # MATIC price

    # Require 2x gas cost as minimum profit
    min_profit = gas_cost_usd * 2

    return gross_profit_usd > min_profit, gas_cost_usd
```

### Emergency Procedures

1. **WebSocket Disconnect:** Fallback to REST polling at reduced frequency
2. **Failed Trade Leg:** Immediately attempt to close open position at market
3. **Gas Spike:** Pause trading until gas normalizes
4. **API Rate Limit:** Exponential backoff (1s, 2s, 4s, 8s...)

---

## 7. Compliance & ToS Safety

### Safe Patterns (from analyses)

1. **Price Discovery Arbitrage** - Exploiting price differences (allowed)
2. **Copy Trading** - Following public blockchain data (allowed)
3. **Cross-Platform Trading** - Different platforms, same event (allowed)
4. **Limit Order Market Making** - Providing liquidity (allowed)

### Avoid These (ToS Risks)

1. **Wash Trading** - Trading with yourself to inflate volume
2. **Market Manipulation** - Coordinated pump/dump schemes
3. **Front-Running Internal Data** - Using non-public information
4. **Bot Swarms** - Multiple accounts/bots to circumvent limits
5. **Excessive API Abuse** - Hammering endpoints (rate limits exist)

### Private Key Safety

```python
# WRONG: Hardcoded key
PRIVATE_KEY = "0x123..."

# BETTER: Environment variable
import os
PRIVATE_KEY = os.environ.get("POLY_PRIVATE_KEY")

# BEST: Encrypted keystore or hardware wallet
from eth_account import Account
keystore = Account.decrypt(keyfile_json, password)
```

---

## 8. Production Deployment

### Infrastructure Recommendations

**For $100 Capital:**

| Component | Recommended | Cost | Alternative |
|-----------|-------------|------|-------------|
| VPS | DigitalOcean Droplet $6/mo | $6/mo | Local machine |
| RPC | Alchemy Free Tier | Free | QuickNode $9/mo |
| Monitoring | Discord/Telegram webhook | Free | Grafana (overkill) |
| Database | SQLite (local file) | Free | PostgreSQL (overkill) |

**Total Monthly Cost:** $6-15

### Deployment Checklist

```markdown
- [ ] Environment variables secured (.env, not committed)
- [ ] Private key NOT in code
- [ ] Kill switch tested and working
- [ ] WebSocket reconnection logic tested
- [ ] Logging enabled for all trades
- [ ] Error alerting configured (Telegram bot)
- [ ] Backup strategy if primary fails
- [ ] Daily PnL reporting automated
```

### Recommended Stack

```
Python 3.10+
├── websockets (WebSocket handling)
├── web3.py (Blockchain interaction)
├── eth-account (Transaction signing)
├── aiohttp (Async HTTP)
├── sqlite3 (Persistence)
└── python-telegram-bot (Alerting)
```

### Startup Script Template

```python
#!/usr/bin/env python3
import asyncio
import logging
from bot import TradingBot
from risk import KillSwitch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    kill_switch = KillSwitch(max_daily_loss=10)
    bot = TradingBot(kill_switch=kill_switch)

    try:
        logger.info("Starting Polymarket Arbitrage Bot...")
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        await bot.stop()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        await bot.emergency_stop()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 9. Repository Rankings Summary

### For $100 Capital Deployment

| Rank | Repository | Strategy | Difficulty | Viability |
|------|-----------|----------|------------|-----------|
| 1 | crypmancer/polymarket-arbitrage-copy-bot | Copy Trading | Easy | 8/10 |
| 2 | hodlwarden/polymarket-arbitrage-copy-bot | Copy Trading (Advanced) | Medium | 8/10 |
| 3 | realfishsam/prediction-market-arbitrage-bot | Cross-Platform | Medium | 8/10 |
| 4 | coleschaffer/Gabagool | Cross-Platform + UI | Hard | 6/10 |
| 5 | Jonmaa/btc-polymarket-bot | TA Prediction | Easy | 5/10 |
| 6 | cakaroni/polymarket-arbitrage-bot-btc-eth-15m | Time-Window | Hard | 3/10 |
| 7 | apemoonspin/polymarket-arbitrage-trading-bot | Bundle (deprecated) | Easy | 2/10 |
| 8 | CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot | Cross-Platform (Kalshi) | Medium | 2/10 |
| 9 | 0xRustElite1111/polymarket-arbitrage-trading-bot | HFT (Rust) | Expert | 2/10 |

### For Learning/Reference

| Rank | Repository | Best For Learning |
|------|-----------|-------------------|
| 1 | 0xRustElite1111 | High-performance architecture |
| 2 | hodlwarden | Raw transaction signing, MEV |
| 3 | apemoonspin | Fee calculations, data logging |
| 4 | CarlosIbCu | Exchange interface abstraction |
| 5 | Gabagool | Full-stack TypeScript patterns |

---

## 10. Quick Start Guide for $100 Bot

### Step 1: Choose Strategy
- **Beginner:** Copy Trading (crypmancer)
- **Intermediate:** Cross-Platform (realfishsam)
- **Advanced:** Copy Trading + Raw TX (hodlwarden)

### Step 2: Setup Environment
```bash
# Clone chosen repo
git clone https://github.com/crypmancer/polymarket-arbitrage-copy-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your keys
```

### Step 3: Fund Wallet
- Create Polygon wallet (MetaMask)
- Bridge USDC to Polygon
- Deposit $100 to Polymarket

### Step 4: Configure Bot
```python
# config.py
WHALE_ADDRESSES = [
    "0x...",  # Top trader 1
    "0x...",  # Top trader 2
]

MIN_COPY_SIZE = 5  # $5 minimum
MAX_COPY_SIZE = 25  # $25 maximum
MAX_DAILY_LOSS = 10  # $10 stop
```

### Step 5: Run in Research Mode First
```python
# Set ENABLE_TRADING = False
# Run for 24-48 hours
# Analyze logged opportunities
# Verify whale quality
```

### Step 6: Go Live
```python
# Set ENABLE_TRADING = True
# Start with 50% of planned size
# Monitor first 10 trades manually
# Scale up after validation
```

---

## Appendix: Code Snippet Index

| Module | Source Repo | Location in This Doc |
|--------|-------------|---------------------|
| Fee-Aware Detection | apemoonspin | Section 1 |
| Exchange Interface | CarlosIbCu | Section 1 |
| Whale Decoder | crypmancer | Section 1 |
| WebSocket Handler | realfishsam | Section 2 |
| Data Logger | apemoonspin | Section 2 |
| Raw TX Builder | hodlwarden | Section 2 |
| Position Sizer | crypmancer | Section 3 |
| Risk Manager | hodlwarden | Section 3 |
| Gas Optimizer | hodlwarden | Section 3 |
| Spot Oracle | cakaroni | Section 3 |
| Kill Switch | hodlwarden | Section 6 |

---

*Document compiled from Level 2 analyses of 9 Polymarket arbitrage bot repositories*
*For questions or updates, see: docs/level2_analysis/*
