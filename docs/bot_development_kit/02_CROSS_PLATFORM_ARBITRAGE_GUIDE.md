# Cross-Platform Arbitrage Guide - Secondary Strategy

## What is Cross-Platform Arbitrage?

Cross-platform arbitrage exploits **price differences for the same event** across different prediction markets (Polymarket, Manifold, Kalshi).

**Example:**
- Polymarket: "Trump wins 2024" = $0.55
- Manifold: "Trump wins 2024" = $0.62
- **Opportunity:** Buy on Poly at $0.55, sell on Manifold at $0.62 = $0.07 profit

**Why it works:**
- Different user bases have different beliefs
- Liquidity varies by platform
- Information propagates at different speeds
- Market mechanisms differ (CLOB vs AMM)

---

## Best Implementation

### realfishsam/prediction-market-arbitrage-bot

**Viability:** 8/10 | **Difficulty:** Medium | **Focus:** Polymarket + Manifold

**Why Recommended:**
- Clean async Python architecture
- WebSocket implementation for real-time data
- Well-documented market matching
- Proven in production

**Key Features:**
- Concurrent price fetching from both platforms
- Configurable spread threshold (default 5%)
- Basic atomic execution pattern
- Error recovery for partial fills

---

## Platform Comparison

| Platform | Min Capital | API Latency | KYC Required | Settlement |
|----------|-------------|-------------|--------------|------------|
| **Polymarket** | $10 | 50-100ms | No | Blockchain (Polygon) |
| **Manifold** | $5 | 100-200ms | No | Off-chain (DB) |
| **Kalshi** | $100+ | 200-500ms | Yes (US only) | Regulated CFTC |

### Recommended Pair: Polymarket + Manifold

**Why Manifold over Kalshi for $25 capital:**

1. **Lower minimum:** $5 vs $100
2. **No KYC:** Instant start vs days of verification
3. **Simpler API:** REST/WebSocket vs complex trading API
4. **Better spreads:** Less efficient = more opportunities
5. **No withdrawal delays:** Kalshi holds funds

---

## How It Works

### Detection Phase

```python
# From: realfishsam/prediction-market-arbitrage-bot
import asyncio

async def check_arbitrage_pair(poly_market_id, manifold_market_id):
    """
    Concurrently fetch prices and check for arbitrage
    """
    # Fetch both prices simultaneously
    poly_price, manifold_price = await asyncio.gather(
        poly_client.get_best_ask(poly_market_id),
        manifold_client.get_best_bid(manifold_market_id)
    )

    # Calculate spread (buy poly, sell manifold)
    spread_a = manifold_price - poly_price

    # Opposite direction (buy manifold, sell poly)
    poly_bid = await poly_client.get_best_bid(poly_market_id)
    manifold_ask = await manifold_client.get_best_ask(manifold_market_id)
    spread_b = poly_bid - manifold_ask

    # Check if profitable (after fees)
    poly_fee = 0.02  # ~2% maker fee
    manifold_fee = 0.00  # Usually 0% for makers

    net_spread_a = spread_a - (poly_fee * poly_price) - (manifold_fee * manifold_price)
    net_spread_b = spread_b - (poly_fee * poly_bid) - (manifold_fee * manifold_ask)

    if net_spread_a > 0.03:  # 3% minimum after fees
        return {
            'direction': 'BUY_POLY_SELL_MANIFOLD',
            'spread': net_spread_a,
            'poly_price': poly_price,
            'manifold_price': manifold_price
        }

    if net_spread_b > 0.03:
        return {
            'direction': 'BUY_MANIFOLD_SELL_POLY',
            'spread': net_spread_b,
            'poly_price': poly_bid,
            'manifold_price': manifold_ask
        }

    return None  # No arbitrage
```

### Execution Phase

```python
async def execute_arbitrage(signal: dict, size: float):
    """
    Execute arbitrage trade on both platforms

    WARNING: Not truly atomic - legging risk exists
    """
    try:
        if signal['direction'] == 'BUY_POLY_SELL_MANIFOLD':
            # Execute both legs concurrently
            poly_order, manifold_order = await asyncio.gather(
                poly_client.buy(
                    market_id=signal['poly_market_id'],
                    price=signal['poly_price'],
                    amount=size
                ),
                manifold_client.sell(
                    market_id=signal['manifold_market_id'],
                    price=signal['manifold_price'],
                    amount=size
                )
            )

            # Verify both filled
            if poly_order['filled'] and manifold_order['filled']:
                profit = (manifold_order['fill_price'] - poly_order['fill_price']) * size
                return {'success': True, 'profit': profit}
            else:
                # Partial fill - need to unwind
                await handle_partial_fill(poly_order, manifold_order)
                return {'success': False, 'reason': 'partial_fill'}

    except Exception as e:
        logger.error(f"Arbitrage execution failed: {e}")
        return {'success': False, 'reason': str(e)}
```

---

## Market Matching

### The Challenge

Polymarket and Manifold use different market IDs and naming conventions:
- Polymarket: `0x1234...` (condition ID)
- Manifold: `trump-wins-2024-presidential-election`

### Manual Mapping Approach

```python
# config/market_pairs.json
MARKET_PAIRS = [
    {
        "name": "Trump wins 2024",
        "poly_id": "0x1234567890abcdef...",
        "manifold_id": "trump-wins-2024-presidential-election",
        "category": "politics"
    },
    {
        "name": "BTC > $100k by Dec 2024",
        "poly_id": "0xabcdef123456...",
        "manifold_id": "bitcoin-above-100k-december-2024",
        "category": "crypto"
    }
]
```

### Semi-Automated Matching

```python
from difflib import SequenceMatcher

def find_matching_market(poly_market_title, manifold_markets):
    """
    Find best matching Manifold market for a Polymarket title
    Uses fuzzy string matching
    """
    best_match = None
    best_score = 0

    for manifold_market in manifold_markets:
        # Clean titles for comparison
        poly_clean = poly_market_title.lower().strip()
        manifold_clean = manifold_market['question'].lower().strip()

        # Calculate similarity
        score = SequenceMatcher(None, poly_clean, manifold_clean).ratio()

        if score > best_score and score > 0.7:  # 70% minimum similarity
            best_score = score
            best_match = manifold_market

    return best_match, best_score
```

**Recommendation:** Start with manual mapping for 5-10 high-volume markets, then expand.

---

## Capital Requirements ($25 Reserve)

### Split Strategy

```
Arbitrage Reserve: $25
├── Polymarket: $15 (60%)
│   └── For buying YES/NO tokens
├── Manifold: $10 (40%)
│   └── For selling positions
└── Note: Rebalance weekly as needed
```

### Why 60/40 Split

- Polymarket has higher volume (more opportunities start here)
- Manifold often overpriced (sell side more common)
- Adjust based on observed patterns

### Minimum Trade Size

```python
def calculate_min_trade(poly_price, manifold_price, spread):
    """
    Calculate minimum trade size to be profitable after gas
    """
    gas_cost_usd = 0.01  # ~$0.01 on Polygon
    min_profit = gas_cost_usd * 3  # 3x gas as minimum

    # Profit = spread * size
    # size = min_profit / spread
    min_size = min_profit / spread

    return max(min_size, 2.0)  # At least $2 per trade
```

---

## Risk Management

### Legging Risk

**The Problem:**
You buy on Polymarket, but Manifold sale fails. Now you're stuck with a position.

**Mitigation Strategies:**

```python
class ArbitrageRiskManager:
    def __init__(self, max_unhedged_exposure=5):
        self.max_unhedged = max_unhedged_exposure  # $5 max stuck position
        self.current_unhedged = 0

    async def safe_execute(self, signal, size):
        """
        Execute with fallback if one leg fails
        """
        # First leg (usually lower risk platform)
        first_result = await execute_first_leg(signal, size)

        if not first_result['success']:
            return {'success': False, 'reason': 'first_leg_failed'}

        # Second leg
        second_result = await execute_second_leg(signal, size)

        if not second_result['success']:
            # CRITICAL: Unwind first leg
            self.current_unhedged += size

            if self.current_unhedged > self.max_unhedged:
                # Force close at market price
                await emergency_close_first_leg(first_result)
                self.current_unhedged -= size

            return {'success': False, 'reason': 'second_leg_failed'}

        return {'success': True, 'profit': calculate_profit(first_result, second_result)}
```

### Position Limits

```python
# For $25 arbitrage reserve
ARB_MAX_PER_TRADE = 5       # $5 max per arbitrage
ARB_MAX_OPEN = 3            # 3 concurrent arbitrages max
ARB_MAX_EXPOSURE = 15       # $15 max total deployed
ARB_MIN_SPREAD = 0.03       # 3% minimum spread
```

### Kill Switch

```python
class ArbKillSwitch:
    def __init__(self):
        self.max_daily_loss = 3     # $3 daily loss limit (12% of $25)
        self.max_failed_trades = 5  # Stop after 5 failed executions
        self.daily_pnl = 0
        self.failed_count = 0
        self.is_active = True

    def record_result(self, success, pnl):
        if success:
            self.daily_pnl += pnl
            self.failed_count = 0
        else:
            self.failed_count += 1

        if self.daily_pnl < -self.max_daily_loss:
            self.trigger("Daily loss limit hit")

        if self.failed_count >= self.max_failed_trades:
            self.trigger("Too many failed trades")

    def trigger(self, reason):
        self.is_active = False
        send_alert(f"ARB KILL SWITCH: {reason}")
```

---

## Expected Opportunities

### Frequency

| Time Period | Opportunities | Avg Spread | Notes |
|-------------|---------------|------------|-------|
| Quiet day | 0-2 | 3-5% | Low volume, few mispricings |
| Normal day | 2-5 | 4-7% | Regular opportunities |
| News event | 5-15 | 5-15% | Price dislocations |
| Election/Major | 10-30+ | 10-25% | Maximum opportunity |

### Historical Data (from analyses)

- **realfishsam reported:** 2-8 opportunities/day on Poly+Manifold
- **Average spread captured:** 5-8%
- **Win rate:** 85%+ (when properly executed)
- **Failure rate:** 15% (partial fills, timing issues)

---

## Code Implementation

### Complete Arbitrage Scanner

```python
"""
Cross-Platform Arbitrage Scanner
Source: Based on realfishsam/prediction-market-arbitrage-bot
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Optional, List
import websockets
import logging

logger = logging.getLogger(__name__)

@dataclass
class ArbOpportunity:
    poly_market_id: str
    manifold_market_id: str
    direction: str
    poly_price: float
    manifold_price: float
    spread: float
    estimated_profit: float

class CrossPlatformScanner:
    def __init__(self, config: dict):
        self.config = config
        self.market_pairs = config['market_pairs']
        self.min_spread = config.get('min_spread', 0.03)
        self.poly_orderbooks = {}
        self.manifold_prices = {}

    async def start(self):
        """Start scanning both platforms"""
        await asyncio.gather(
            self.connect_polymarket_ws(),
            self.poll_manifold_prices()
        )

    async def connect_polymarket_ws(self):
        """WebSocket connection to Polymarket CLOB"""
        uri = "wss://ws-subscriptions-clob.polymarket.com/ws"

        async with websockets.connect(uri) as ws:
            # Subscribe to relevant markets
            for pair in self.market_pairs:
                await ws.send(json.dumps({
                    "type": "subscribe",
                    "channel": "book",
                    "market": pair['poly_id']
                }))

            async for message in ws:
                data = json.loads(message)
                await self.process_poly_update(data)

    async def poll_manifold_prices(self):
        """Poll Manifold API (no public WebSocket)"""
        while True:
            for pair in self.market_pairs:
                try:
                    price = await self.fetch_manifold_price(pair['manifold_id'])
                    self.manifold_prices[pair['manifold_id']] = price

                    # Check for arbitrage after each update
                    await self.check_arbitrage(pair)

                except Exception as e:
                    logger.error(f"Manifold fetch error: {e}")

            await asyncio.sleep(5)  # 5 second polling interval

    async def fetch_manifold_price(self, market_id: str) -> dict:
        """Fetch current price from Manifold"""
        # Implementation using aiohttp
        async with aiohttp.ClientSession() as session:
            url = f"https://api.manifold.markets/v0/market/{market_id}"
            async with session.get(url) as resp:
                data = await resp.json()
                return {
                    'probability': data['probability'],
                    'volume': data.get('volume', 0)
                }

    async def check_arbitrage(self, pair: dict) -> Optional[ArbOpportunity]:
        """Check if arbitrage exists for a market pair"""
        poly_book = self.poly_orderbooks.get(pair['poly_id'])
        manifold_price = self.manifold_prices.get(pair['manifold_id'])

        if not poly_book or not manifold_price:
            return None

        poly_best_ask = poly_book['asks'][0]['price'] if poly_book['asks'] else None
        poly_best_bid = poly_book['bids'][0]['price'] if poly_book['bids'] else None

        if not poly_best_ask or not poly_best_bid:
            return None

        manifold_prob = manifold_price['probability']

        # Direction A: Buy Poly, Sell Manifold
        spread_a = manifold_prob - poly_best_ask
        if spread_a > self.min_spread:
            return ArbOpportunity(
                poly_market_id=pair['poly_id'],
                manifold_market_id=pair['manifold_id'],
                direction='BUY_POLY_SELL_MANIFOLD',
                poly_price=poly_best_ask,
                manifold_price=manifold_prob,
                spread=spread_a,
                estimated_profit=spread_a * 5  # $5 trade
            )

        # Direction B: Buy Manifold, Sell Poly
        spread_b = poly_best_bid - manifold_prob
        if spread_b > self.min_spread:
            return ArbOpportunity(
                poly_market_id=pair['poly_id'],
                manifold_market_id=pair['manifold_id'],
                direction='BUY_MANIFOLD_SELL_POLY',
                poly_price=poly_best_bid,
                manifold_price=manifold_prob,
                spread=spread_b,
                estimated_profit=spread_b * 5
            )

        return None
```

---

## Platform-Specific Notes

### Polymarket

**API Endpoints:**
- REST: `https://clob.polymarket.com`
- WebSocket: `wss://ws-subscriptions-clob.polymarket.com/ws`

**Order Types:** Limit orders only (CLOB)

**Fees:** ~2% maker, ~2% taker

**Settlement:** On-chain (Polygon), ~2 seconds

### Manifold

**API Endpoints:**
- REST: `https://api.manifold.markets/v0`
- No public WebSocket (use polling)

**Order Types:** Market orders (AMM-based)

**Fees:** 0% for most trades

**Settlement:** Instant (database)

**API Docs:** https://docs.manifold.markets/api

---

## Checklist Before Going Live

- [ ] Market pairs mapped (5-10 high-volume markets)
- [ ] Both platform accounts funded ($15 Poly, $10 Manifold)
- [ ] WebSocket connection stable (24hr test)
- [ ] Spread threshold calibrated (backtest historical data)
- [ ] Legging risk handler tested
- [ ] Kill switch configured
- [ ] Alerts working
- [ ] Paper trading validated for 48+ hours

---

## Common Pitfalls

### 1. Stale Prices

**Problem:** Manifold price from 5 seconds ago, Poly moved
**Solution:** Always re-fetch before execution

### 2. Liquidity Mismatch

**Problem:** $5 available on Poly, $50 on Manifold
**Solution:** Size based on smaller liquidity

### 3. Market Resolution Mismatch

**Problem:** Same event, different resolution criteria
**Solution:** Carefully verify market terms match exactly

### 4. Timezone Issues

**Problem:** Markets close at different times
**Solution:** Track resolution times, stop trading 24h before

---

*Next: [03_ARCHITECTURE_BLUEPRINT.md](03_ARCHITECTURE_BLUEPRINT.md)*
