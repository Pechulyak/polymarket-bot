# Architecture Blueprint - Hybrid Bot System

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      HYBRID BOT SYSTEM                          │
│                    ($100 Capital Target)                        │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌───────────────┐
│   WebSocket   │   │    Mempool      │   │    REST       │
│   Manager     │   │    Monitor      │   │   Poller      │
│  (Real-time)  │   │  (Whale TXs)    │   │  (Fallback)   │
└───────┬───────┘   └────────┬────────┘   └───────┬───────┘
        │                    │                     │
        └─────────────┬──────┴─────────────────────┘
                      │
                      ▼
        ┌─────────────────────────────┐
        │      Event Dispatcher       │
        │   (Unified event stream)    │
        └─────────────┬───────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
┌─────────────┐ ┌───────────┐ ┌─────────────┐
│    Copy     │ │ Arbitrage │ │   Signal    │
│   Engine    │ │  Engine   │ │  Aggregator │
│  ($70 cap)  │ │ ($25 cap) │ │ (Analytics) │
└──────┬──────┘ └─────┬─────┘ └─────────────┘
       │              │
       └──────┬───────┘
              │
              ▼
    ┌─────────────────────┐
    │    Risk Manager     │
    │    (Unified)        │
    │  - Kill Switch      │
    │  - Position Limits  │
    │  - Gas Management   │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │   Order Executor    │
    │  - REST API Mode    │
    │  - Raw TX Mode      │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │     Persistence     │
    │  - SQLite (trades)  │
    │  - Redis (state)    │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │      Alerting       │
    │  - Telegram Bot     │
    │  - Log Files        │
    └─────────────────────┘
```

---

## Technology Stack

### Recommended (Consensus from 9 analyses)

| Layer | Technology | Justification |
|-------|------------|---------------|
| **Language** | Python 3.11+ | 7/9 repos use Python, rich ecosystem |
| **Async Framework** | asyncio + aiohttp | Native async, no external deps |
| **WebSocket** | websockets | Standard, well-documented |
| **Blockchain** | web3.py 6.x | Official library, raw tx support |
| **Signing** | eth-account | Direct private key signing |
| **Database** | SQLite + Redis | Simple + fast state |
| **Monitoring** | python-telegram-bot | Real-time alerts |
| **Logging** | logging + structlog | Structured logs for analysis |

### Why Python (Not Rust/TypeScript)

| Factor | Python | Rust | TypeScript |
|--------|--------|------|------------|
| Development Speed | Fast | Slow | Medium |
| Latency | 50-200ms | 1-10ms | 20-100ms |
| Ecosystem | Excellent | Limited | Good |
| Maintenance | Easy | Hard | Medium |
| $100 Bot Need | Sufficient | Overkill | Sufficient |

**Verdict:** Python latency (50-200ms) is sufficient for copy trading and cross-platform arb. Rust only needed for HFT.

---

## Core Components

### 1. WebSocket Manager

**Purpose:** Real-time data feeds from Polymarket and Manifold

**Why Critical:** WebSocket is 75-3000x faster than REST polling

```python
"""
WebSocket Manager - Multi-connection handler
Source: Consolidated from realfishsam + hodlwarden
"""

import asyncio
import json
import websockets
from typing import Callable, Dict, Any
import logging

logger = logging.getLogger(__name__)

class WebSocketManager:
    def __init__(self):
        self.connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.callbacks: Dict[str, Callable] = {}
        self.reconnect_delay = 1
        self.max_reconnect_delay = 60

    async def connect(self, name: str, uri: str, on_message: Callable):
        """
        Establish WebSocket connection with auto-reconnect
        """
        self.callbacks[name] = on_message

        while True:
            try:
                async with websockets.connect(
                    uri,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    self.connections[name] = ws
                    self.reconnect_delay = 1  # Reset on success
                    logger.info(f"Connected to {name}")

                    async for message in ws:
                        try:
                            data = json.loads(message)
                            await on_message(data)
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid JSON from {name}")

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Connection {name} closed: {e}")
            except Exception as e:
                logger.error(f"WebSocket error {name}: {e}")

            # Reconnect with exponential backoff
            await asyncio.sleep(self.reconnect_delay)
            self.reconnect_delay = min(
                self.reconnect_delay * 2,
                self.max_reconnect_delay
            )
            logger.info(f"Reconnecting to {name}...")

    async def subscribe_polymarket(self, market_ids: list):
        """Subscribe to Polymarket orderbook updates"""
        ws = self.connections.get('polymarket')
        if ws:
            for market_id in market_ids:
                await ws.send(json.dumps({
                    "type": "subscribe",
                    "channel": "book",
                    "market": market_id
                }))

    async def close_all(self):
        """Gracefully close all connections"""
        for name, ws in self.connections.items():
            await ws.close()
            logger.info(f"Closed {name}")
```

**Endpoints:**

| Platform | WebSocket URL | Notes |
|----------|---------------|-------|
| Polymarket CLOB | `wss://ws-subscriptions-clob.polymarket.com/ws` | Orderbook updates |
| Polygon WSS | `wss://polygon-mainnet.g.alchemy.com/v2/{API_KEY}` | Mempool monitoring |
| Manifold | N/A (poll REST) | No public WebSocket |

---

### 2. Copy Trading Engine

**Purpose:** Detect and copy whale trades with proportional sizing

```python
"""
Copy Trading Engine
Source: crypmancer + hodlwarden patterns
"""

from dataclasses import dataclass
from typing import Optional, Set
from web3 import Web3
import asyncio

@dataclass
class WhaleSignal:
    address: str
    market_id: str
    side: str  # "BUY" or "SELL"
    amount: float
    price: float
    tx_hash: str
    block_number: int

class CopyTradingEngine:
    def __init__(self, config: dict, risk_manager, executor):
        self.config = config
        self.risk_manager = risk_manager
        self.executor = executor
        self.tracked_whales: Set[str] = set(config['whale_addresses'])
        self.whale_positions: dict = {}  # Track what whales hold
        self.my_positions: dict = {}

    async def process_transaction(self, tx: dict) -> Optional[dict]:
        """
        Process a detected transaction and decide whether to copy
        """
        # Check if from tracked whale
        sender = tx.get('from', '').lower()
        if sender not in self.tracked_whales:
            return None

        # Decode the trade
        signal = self.decode_trade(tx)
        if not signal:
            return None

        # Check if opening (not closing) position
        if not self.is_opening_trade(signal):
            # Whale is exiting - check if we should exit too
            return await self.handle_whale_exit(signal)

        # Calculate copy size
        copy_size = self.calculate_copy_size(signal)
        if copy_size == 0:
            return None

        # Risk check
        can_trade, reason = self.risk_manager.can_trade(
            market_id=signal.market_id,
            size=copy_size,
            strategy='copy'
        )
        if not can_trade:
            logger.info(f"Risk check failed: {reason}")
            return None

        # Execute copy trade
        result = await self.executor.execute(
            market_id=signal.market_id,
            side=signal.side,
            size=copy_size,
            price=signal.price,
            mode='rest'  # Copy trading uses REST (lower latency not critical)
        )

        if result['success']:
            self.my_positions[signal.market_id] = {
                'size': copy_size,
                'entry_price': result['fill_price'],
                'whale': signal.address
            }

        return result

    def decode_trade(self, tx: dict) -> Optional[WhaleSignal]:
        """Decode Polymarket CLOB transaction"""
        # Implementation using ABI decoding
        pass

    def is_opening_trade(self, signal: WhaleSignal) -> bool:
        """Check if whale is opening or closing"""
        existing = self.whale_positions.get(
            (signal.address, signal.market_id)
        )
        if existing is None:
            return True
        if existing['side'] == signal.side:
            return True  # Adding to position
        return False  # Closing

    def calculate_copy_size(self, signal: WhaleSignal) -> float:
        """Proportional sizing based on whale conviction"""
        whale_balance = self.config['whale_balances'].get(
            signal.address, 100000
        )
        my_balance = self.config['copy_capital']  # $70

        conviction = signal.amount / whale_balance
        base_size = my_balance * conviction

        # Apply limits
        if base_size < self.config['min_copy_size']:
            return 0
        return min(base_size, self.config['max_copy_size'])
```

---

### 3. Arbitrage Engine

**Purpose:** Detect and execute cross-platform price discrepancies

```python
"""
Arbitrage Detection Engine
Source: realfishsam architecture
"""

from dataclasses import dataclass
from typing import Optional, List
import asyncio

@dataclass
class ArbOpportunity:
    pair_name: str
    direction: str
    poly_price: float
    manifold_price: float
    spread: float
    size: float
    expected_profit: float

class ArbitrageEngine:
    def __init__(self, config: dict, risk_manager, executor):
        self.config = config
        self.risk_manager = risk_manager
        self.executor = executor
        self.market_pairs = config['market_pairs']
        self.min_spread = config.get('min_spread', 0.03)

        # State
        self.poly_orderbooks: dict = {}
        self.manifold_prices: dict = {}

    def update_poly_orderbook(self, market_id: str, book: dict):
        """Update local orderbook state from WebSocket"""
        self.poly_orderbooks[market_id] = book

    def update_manifold_price(self, market_id: str, price: float):
        """Update Manifold price from polling"""
        self.manifold_prices[market_id] = price

    def scan_opportunities(self) -> List[ArbOpportunity]:
        """Scan all pairs for arbitrage opportunities"""
        opportunities = []

        for pair in self.market_pairs:
            opp = self.check_pair(pair)
            if opp:
                opportunities.append(opp)

        # Sort by expected profit
        return sorted(opportunities, key=lambda x: -x.expected_profit)

    def check_pair(self, pair: dict) -> Optional[ArbOpportunity]:
        """Check single pair for arbitrage"""
        poly_book = self.poly_orderbooks.get(pair['poly_id'])
        manifold_price = self.manifold_prices.get(pair['manifold_id'])

        if not poly_book or manifold_price is None:
            return None

        poly_ask = self.get_best_ask(poly_book)
        poly_bid = self.get_best_bid(poly_book)

        if not poly_ask or not poly_bid:
            return None

        # Check both directions
        # Direction A: Buy Poly, Sell Manifold
        spread_a = manifold_price - poly_ask - self.estimate_fees(poly_ask, manifold_price)

        if spread_a > self.min_spread:
            size = self.calculate_arb_size(poly_book, spread_a)
            return ArbOpportunity(
                pair_name=pair['name'],
                direction='BUY_POLY_SELL_MANIFOLD',
                poly_price=poly_ask,
                manifold_price=manifold_price,
                spread=spread_a,
                size=size,
                expected_profit=spread_a * size
            )

        # Direction B: Buy Manifold, Sell Poly
        spread_b = poly_bid - manifold_price - self.estimate_fees(poly_bid, manifold_price)

        if spread_b > self.min_spread:
            size = self.calculate_arb_size(poly_book, spread_b)
            return ArbOpportunity(
                pair_name=pair['name'],
                direction='BUY_MANIFOLD_SELL_POLY',
                poly_price=poly_bid,
                manifold_price=manifold_price,
                spread=spread_b,
                size=size,
                expected_profit=spread_b * size
            )

        return None

    def estimate_fees(self, poly_price: float, manifold_price: float) -> float:
        """Estimate total fees for both legs"""
        poly_fee = poly_price * 0.02  # ~2%
        manifold_fee = 0  # Usually 0%
        return poly_fee + manifold_fee

    async def execute_opportunity(self, opp: ArbOpportunity) -> dict:
        """Execute arbitrage with concurrent orders"""
        can_trade, reason = self.risk_manager.can_trade(
            market_id=opp.pair_name,
            size=opp.size,
            strategy='arbitrage'
        )
        if not can_trade:
            return {'success': False, 'reason': reason}

        # Execute both legs concurrently
        if opp.direction == 'BUY_POLY_SELL_MANIFOLD':
            results = await asyncio.gather(
                self.executor.execute_poly_buy(opp),
                self.executor.execute_manifold_sell(opp)
            )
        else:
            results = await asyncio.gather(
                self.executor.execute_manifold_buy(opp),
                self.executor.execute_poly_sell(opp)
            )

        return self.handle_execution_results(results, opp)
```

---

### 4. Unified Risk Manager

**Purpose:** Central risk control for both strategies

```python
"""
Unified Risk Manager
Source: hodlwarden patterns
"""

from dataclasses import dataclass
from typing import Tuple
import time

@dataclass
class RiskLimits:
    # Global limits
    max_daily_loss: float = 10.0          # $10 total
    max_total_exposure: float = 80.0      # $80 max deployed

    # Copy trading limits ($70 reserve)
    copy_max_position: float = 20.0       # $20 per market
    copy_max_exposure: float = 56.0       # $56 max (80% of $70)
    copy_max_daily_loss: float = 7.0      # $7

    # Arbitrage limits ($25 reserve)
    arb_max_position: float = 5.0         # $5 per trade
    arb_max_exposure: float = 15.0        # $15 max
    arb_max_daily_loss: float = 3.0       # $3

    # Gas limits
    max_gas_gwei: float = 50.0            # Pause if gas > 50 gwei

class UnifiedRiskManager:
    def __init__(self, limits: RiskLimits = None):
        self.limits = limits or RiskLimits()
        self.positions = {}  # market_id -> position
        self.daily_pnl = {'copy': 0.0, 'arbitrage': 0.0}
        self.consecutive_losses = {'copy': 0, 'arbitrage': 0}
        self.is_active = True
        self.kill_reason = None

    def can_trade(
        self,
        market_id: str,
        size: float,
        strategy: str,
        current_gas_gwei: float = 30.0
    ) -> Tuple[bool, str]:
        """
        Check if trade is allowed by risk rules
        Returns (can_trade, reason)
        """
        # Global kill switch
        if not self.is_active:
            return False, f"Kill switch active: {self.kill_reason}"

        # Gas check
        if current_gas_gwei > self.limits.max_gas_gwei:
            return False, f"Gas too high: {current_gas_gwei} gwei"

        # Strategy-specific limits
        if strategy == 'copy':
            return self._check_copy_limits(market_id, size)
        elif strategy == 'arbitrage':
            return self._check_arb_limits(market_id, size)

        return False, "Unknown strategy"

    def _check_copy_limits(self, market_id: str, size: float) -> Tuple[bool, str]:
        """Check copy trading specific limits"""
        # Daily loss check
        if self.daily_pnl['copy'] < -self.limits.copy_max_daily_loss:
            return False, "Copy daily loss limit hit"

        # Position limit
        current_pos = self.positions.get(market_id, {}).get('size', 0)
        if current_pos + size > self.limits.copy_max_position:
            return False, "Copy position limit exceeded"

        # Total exposure
        copy_exposure = sum(
            p['size'] for p in self.positions.values()
            if p.get('strategy') == 'copy'
        )
        if copy_exposure + size > self.limits.copy_max_exposure:
            return False, "Copy exposure limit exceeded"

        return True, "OK"

    def _check_arb_limits(self, market_id: str, size: float) -> Tuple[bool, str]:
        """Check arbitrage specific limits"""
        if self.daily_pnl['arbitrage'] < -self.limits.arb_max_daily_loss:
            return False, "Arb daily loss limit hit"

        if size > self.limits.arb_max_position:
            return False, "Arb position limit exceeded"

        arb_exposure = sum(
            p['size'] for p in self.positions.values()
            if p.get('strategy') == 'arbitrage'
        )
        if arb_exposure + size > self.limits.arb_max_exposure:
            return False, "Arb exposure limit exceeded"

        return True, "OK"

    def record_trade(self, strategy: str, pnl: float, market_id: str = None):
        """Record trade result and check kill conditions"""
        self.daily_pnl[strategy] += pnl

        if pnl < 0:
            self.consecutive_losses[strategy] += 1
        else:
            self.consecutive_losses[strategy] = 0

        # Check kill conditions
        total_daily_loss = sum(self.daily_pnl.values())
        if total_daily_loss < -self.limits.max_daily_loss:
            self.trigger_kill_switch("Total daily loss limit exceeded")

        if self.consecutive_losses[strategy] >= 3:
            self.trigger_kill_switch(f"{strategy}: 3 consecutive losses")

    def trigger_kill_switch(self, reason: str):
        """Activate kill switch"""
        self.is_active = False
        self.kill_reason = reason
        # Alert and close positions handled externally

    def reset_daily(self):
        """Reset daily counters (call at midnight UTC)"""
        self.daily_pnl = {'copy': 0.0, 'arbitrage': 0.0}
        self.consecutive_losses = {'copy': 0, 'arbitrage': 0}
        if self.kill_reason and 'daily' in self.kill_reason.lower():
            self.is_active = True
            self.kill_reason = None
```

---

### 5. Order Executor

**Purpose:** Execute trades via REST API or raw transactions

```python
"""
Order Executor - Dual mode (REST + Raw TX)
Source: hodlwarden raw tx patterns
"""

from web3 import Web3
from eth_account import Account
import aiohttp
import json

class OrderExecutor:
    def __init__(self, config: dict):
        self.config = config
        self.w3 = Web3(Web3.HTTPProvider(config['rpc_url']))
        self.account = Account.from_key(config['private_key'])

        # API clients
        self.poly_api_url = "https://clob.polymarket.com"
        self.manifold_api_url = "https://api.manifold.markets/v0"

    async def execute(
        self,
        market_id: str,
        side: str,
        size: float,
        price: float,
        mode: str = 'rest'
    ) -> dict:
        """
        Execute trade in specified mode

        mode: 'rest' (simpler, slower) or 'raw' (faster, complex)
        """
        if mode == 'raw':
            return await self.execute_raw_tx(market_id, side, size, price)
        else:
            return await self.execute_rest_api(market_id, side, size, price)

    async def execute_rest_api(
        self,
        market_id: str,
        side: str,
        size: float,
        price: float
    ) -> dict:
        """Execute via Polymarket REST API"""
        # Sign order
        order = self.build_order(market_id, side, size, price)
        signature = self.sign_order(order)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.poly_api_url}/order",
                json={**order, "signature": signature},
                headers=self.get_auth_headers()
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        'success': True,
                        'order_id': data['orderID'],
                        'fill_price': price
                    }
                else:
                    error = await resp.text()
                    return {'success': False, 'reason': error}

    async def execute_raw_tx(
        self,
        market_id: str,
        side: str,
        size: float,
        price: float
    ) -> dict:
        """
        Execute via raw transaction (5-10x faster)
        """
        # Build transaction
        nonce = self.w3.eth.get_transaction_count(self.account.address)
        gas_fees = self.get_eip1559_fees()

        contract = self.w3.eth.contract(
            address=self.config['clob_address'],
            abi=self.config['clob_abi']
        )

        tx = contract.functions.createOrder(
            tokenId=market_id,
            side=0 if side == 'BUY' else 1,
            amount=int(size * 1e6),  # USDC decimals
            price=int(price * 1e6)
        ).build_transaction({
            'chainId': 137,  # Polygon
            'gas': 300000,
            'maxFeePerGas': gas_fees['maxFeePerGas'],
            'maxPriorityFeePerGas': gas_fees['maxPriorityFeePerGas'],
            'nonce': nonce
        })

        # Sign and send
        signed = self.w3.eth.account.sign_transaction(tx, self.config['private_key'])
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)

        # Wait for confirmation
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

        return {
            'success': receipt['status'] == 1,
            'tx_hash': tx_hash.hex(),
            'gas_used': receipt['gasUsed']
        }

    def get_eip1559_fees(self, priority: str = 'medium') -> dict:
        """Calculate optimal EIP-1559 gas fees"""
        latest = self.w3.eth.get_block('latest')
        base_fee = latest['baseFeePerGas']

        priority_fees = {
            'low': self.w3.to_wei(1, 'gwei'),
            'medium': self.w3.to_wei(2, 'gwei'),
            'high': self.w3.to_wei(5, 'gwei')
        }

        return {
            'maxFeePerGas': base_fee * 2 + priority_fees[priority],
            'maxPriorityFeePerGas': priority_fees[priority]
        }
```

---

## State Management

### Redis Schema (Real-time State)

```
# Active positions
positions:copy:{market_id} -> {size, entry_price, whale, timestamp}
positions:arb:{pair_name} -> {poly_size, manifold_size, entry_spread}

# Whale tracking
whales:tracked -> Set of addresses
whales:positions:{address}:{market_id} -> {size, side}

# Risk state
risk:daily_pnl:copy -> float
risk:daily_pnl:arb -> float
risk:kill_switch -> "active" | "triggered:{reason}"

# Orderbooks (cached)
orderbook:poly:{market_id} -> {bids, asks, timestamp}
price:manifold:{market_id} -> {probability, timestamp}
```

### SQLite Schema (Persistence)

```sql
-- Trade history
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    strategy TEXT,           -- 'copy' or 'arbitrage'
    market_id TEXT,
    side TEXT,
    size REAL,
    entry_price REAL,
    exit_price REAL,
    pnl REAL,
    whale_address TEXT,      -- For copy trades
    tx_hash TEXT
);

-- Position snapshots
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    market_id TEXT,
    strategy TEXT,
    size REAL,
    entry_price REAL,
    current_price REAL,
    unrealized_pnl REAL
);

-- Daily summaries
CREATE TABLE daily_summary (
    date DATE PRIMARY KEY,
    copy_trades INTEGER,
    copy_pnl REAL,
    arb_trades INTEGER,
    arb_pnl REAL,
    total_pnl REAL,
    gas_cost REAL
);
```

---

## Error Handling

### Retry Strategy

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def execute_with_retry(executor, params):
    """Execute with exponential backoff"""
    return await executor.execute(**params)
```

### Graceful Degradation

```python
class FallbackManager:
    async def get_price(self, market_id: str) -> float:
        """Try WebSocket, fallback to REST"""
        try:
            # Primary: WebSocket cache
            price = self.ws_cache.get(market_id)
            if price and self.is_fresh(price):
                return price['value']

            # Fallback: REST API
            return await self.rest_client.get_price(market_id)

        except Exception as e:
            logger.error(f"Price fetch failed: {e}")
            raise
```

---

## Deployment Architecture

### Development (Local)

```
┌─────────────────────────────────────┐
│         Local Machine               │
│  - Python 3.11                      │
│  - SQLite file                      │
│  - Alchemy Free RPC                 │
│  - Paper trading mode               │
└─────────────────────────────────────┘
```

### Production (VPS)

```
┌─────────────────────────────────────┐
│     VPS ($6-15/month)               │
│  - Ubuntu 22.04                     │
│  - Python 3.11 + venv               │
│  - systemd service                  │
│  - SQLite + Redis                   │
│  - Paid RPC (Alchemy Growth)        │
│  - <50ms to Polygon                 │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│     Monitoring                      │
│  - Telegram Bot (alerts)            │
│  - Log rotation                     │
│  - Daily email summary              │
└─────────────────────────────────────┘
```

---

## File Structure

```
polymarket-bot/
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── config.py               # Configuration
│   ├── engines/
│   │   ├── copy_trading.py     # Copy engine
│   │   └── arbitrage.py        # Arb engine
│   ├── core/
│   │   ├── websocket.py        # WS manager
│   │   ├── executor.py         # Order execution
│   │   └── risk.py             # Risk manager
│   ├── clients/
│   │   ├── polymarket.py       # Poly API wrapper
│   │   └── manifold.py         # Manifold API
│   ├── utils/
│   │   ├── signing.py          # EIP-712 signing
│   │   └── gas.py              # Gas estimation
│   └── alerts/
│       └── telegram.py         # Alerting
├── data/
│   └── trades.db               # SQLite database
├── logs/
│   └── bot.log                 # Log files
├── config/
│   ├── market_pairs.json       # Cross-platform mapping
│   └── whales.json             # Tracked addresses
├── tests/
│   └── ...                     # Test files
├── .env                        # Secrets
├── requirements.txt            # Dependencies
└── README.md
```

---

*Next: [04_CODE_LIBRARY/](04_CODE_LIBRARY/) - Ready-to-use Python modules*
