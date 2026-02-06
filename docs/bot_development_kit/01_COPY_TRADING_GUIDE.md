# Copy Trading Guide - Primary Strategy

## What is Copy Trading?

Copy trading on Polymarket means **following the trades of profitable addresses** (whales) by monitoring the blockchain and replicating their positions proportionally.

**Why it works:**
- Whales have better information/analysis
- You don't need to "outsmart" the market
- Capital only deployed when there's a signal
- Lower cognitive load than active trading

**Key Insight (from analyses):**
> "Instead of competing with whales, ride their wake. A $100 account can follow a $100K trader's moves with proportional sizing."

---

## Best Implementations

### Beginner: crypmancer/polymarket-arbitrage-copy-bot

**Viability:** 8/10 | **Difficulty:** Easy | **Stars:** High activity

**Approach:**
- Block-by-block monitoring (not mempool)
- Simple ABI decoding of CLOB transactions
- Proportional sizing based on whale's trade
- Basic risk management

**Pros:**
- Clean, readable Python code
- Good documentation
- Works with free Alchemy RPC

**Cons:**
- Slower than mempool monitoring (1-2 blocks delay)
- No MEV protection

**Key Code Pattern:**
```python
# From: crypmancer/polymarket-arbitrage-copy-bot
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
```

---

### Advanced: hodlwarden/polymarket-arbitrage-copy-bot

**Viability:** 8/10 | **Difficulty:** Medium | **Stars:** Production-ready

**Approach:**
- Mempool monitoring for pending transactions
- Raw transaction signing (5-10x faster)
- MEV-aware execution with priority fees
- Comprehensive risk management

**Pros:**
- Fastest execution (60ms vs 500ms)
- Can front-run whale's trade confirmation
- Production-hardened code

**Cons:**
- Requires paid RPC with mempool access
- More complex setup
- Higher gas costs for priority

**Key Code Pattern:**
```python
# From: hodlwarden/polymarket-arbitrage-copy-bot
async def monitor_pending_txs(rpc_url, target_address, callback):
    """Monitor mempool for whale's pending transactions"""
    w3 = Web3(Web3.WebsocketProvider(rpc_url))
    tx_filter = w3.eth.filter('pending')

    while True:
        for tx_hash in tx_filter.get_new_entries():
            tx = w3.eth.get_transaction(tx_hash)
            if tx and tx['from'].lower() == target_address.lower():
                if tx.to == POLY_CLOB_ADDR:
                    await callback(tx)
        await asyncio.sleep(0.01)  # 10ms polling
```

---

## Trader Selection

### Finding Profitable Whales

**Data Sources:**

1. **Polymarket Leaderboard**
   - URL: https://polymarket.com/leaderboard
   - Filter by: All-time profit, Win rate, Activity level

2. **Dune Analytics Dashboards**
   - Search: "Polymarket traders"
   - Look for: Consistent profits, reasonable sizing

3. **Polygonscan Analysis**
   - Filter CLOB contract interactions
   - Analyze trade history of top addresses

### Selection Criteria

| Criterion | Threshold | Why |
|-----------|-----------|-----|
| All-time Profit | >$10,000 | Proves skill, not luck |
| Win Rate | >55% | Consistent edge |
| Avg Trade Size | $100-$10,000 | Not too big (liquidity), not too small |
| Activity | 5+ trades/week | Active enough to follow |
| Holding Period | 1-14 days | Not HFT (can't copy), not too slow |
| Diversification | 3+ markets | Not a one-trick pony |

### Red Flags (Avoid These Traders)

- **Win rate >90%:** Likely insider trading or wash trading
- **Only profitable in one market:** Lucky, not skilled
- **Trades >$50K:** Liquidity exhausted before your fill
- **Trades <$50:** Gas costs exceed profits
- **Only long OR short:** One-dimensional strategy

---

## Position Sizing ($70 Reserve)

### Proportional Sizing Formula

```python
def calculate_copy_size(whale_trade_amount, whale_estimated_balance, my_balance):
    """
    Copy whale's trade proportionally based on their conviction

    Example:
    - Whale has $100,000 balance, trades $5,000 (5% conviction)
    - You have $70 balance -> trade $3.50 (5% conviction)
    """
    conviction_ratio = whale_trade_amount / whale_estimated_balance
    my_trade_size = my_balance * conviction_ratio

    # Apply caps
    MIN_TRADE_SIZE = 5   # $5 minimum (gas efficiency)
    MAX_TRADE_SIZE = 20  # $20 maximum (risk management)

    if my_trade_size < MIN_TRADE_SIZE:
        return 0  # Skip trade - too small
    if my_trade_size > MAX_TRADE_SIZE:
        return MAX_TRADE_SIZE

    return my_trade_size
```

### Sizing Examples for $70 Capital

| Whale Trade | Whale Balance | Conviction | Your Trade |
|-------------|---------------|------------|------------|
| $1,000 | $100,000 | 1% | Skip ($0.70 < $5 min) |
| $5,000 | $100,000 | 5% | $5 (minimum) |
| $10,000 | $100,000 | 10% | $7 |
| $25,000 | $100,000 | 25% | $17.50 |
| $50,000 | $100,000 | 50% | $20 (capped) |

### Signal Strength Multiplier

```python
def enhanced_position_size(base_size, signal_strength):
    """
    Adjust size based on signal quality

    signal_strength:
    - "LOW": Single whale, small trade
    - "MEDIUM": Single whale, large trade OR multiple whales agree
    - "HIGH": Multiple whales, large trades, same direction
    """
    multipliers = {
        "LOW": 0.5,      # Half size
        "MEDIUM": 1.0,   # Normal size
        "HIGH": 1.5      # 150% size (still capped at max)
    }

    return min(base_size * multipliers[signal_strength], MAX_TRADE_SIZE)
```

---

## Risk Management

### Position Limits

```python
# For $70 copy trading reserve
MAX_POSITION_PER_MARKET = 15    # $15 max in any single market
MAX_TOTAL_EXPOSURE = 56         # $56 max deployed (80% of $70)
MIN_CASH_RESERVE = 14           # $14 always in cash (20%)
MAX_CONCURRENT_POSITIONS = 5    # Max 5 markets at once
```

### Kill Switch Implementation

```python
class CopyTradingKillSwitch:
    def __init__(self):
        self.max_daily_loss = 7          # $7 daily loss limit (10% of $70)
        self.max_consecutive_losses = 3   # 3 losses in a row
        self.daily_pnl = 0
        self.consecutive_losses = 0
        self.is_active = True

    def record_trade(self, pnl):
        self.daily_pnl += pnl

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # Check kill conditions
        if self.daily_pnl < -self.max_daily_loss:
            self.trigger("Daily loss limit: ${:.2f}".format(abs(self.daily_pnl)))

        if self.consecutive_losses >= self.max_consecutive_losses:
            self.trigger(f"{self.consecutive_losses} consecutive losses")

    def trigger(self, reason):
        self.is_active = False
        send_telegram_alert(f"KILL SWITCH: {reason}")
        # Close all open positions at market
        close_all_positions()

    def reset_daily(self):
        """Call at midnight UTC"""
        self.daily_pnl = 0
        self.consecutive_losses = 0
        self.is_active = True
```

### Entry/Exit Rules

**Entry Conditions (all must be true):**
1. Whale is in tracked list
2. Trade size > minimum threshold
3. Market has sufficient liquidity
4. Kill switch is active
5. Within position limits
6. Gas price is reasonable (<50 gwei)

**Exit Conditions (any triggers exit):**
1. Whale exits position (primary)
2. Profit target hit (20%+ profit)
3. Stop loss hit (15% loss)
4. Market expires soon (<24 hours)
5. Kill switch triggered

---

## Code Implementation

### Complete Copy Trading Engine

```python
"""
Copy Trading Engine for Polymarket
Source: Consolidated from crypmancer + hodlwarden analyses
"""

import asyncio
from web3 import Web3
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class WhaleSignal:
    whale_address: str
    market_id: str
    side: str  # "BUY" or "SELL"
    amount: float
    price: float
    tx_hash: str

class CopyTradingEngine:
    def __init__(self, w3: Web3, private_key: str, config: dict):
        self.w3 = w3
        self.account = w3.eth.account.from_key(private_key)
        self.config = config
        self.tracked_whales = set(config['whale_addresses'])
        self.positions = {}  # market_id -> position
        self.kill_switch = CopyTradingKillSwitch()

    async def process_whale_trade(self, signal: WhaleSignal) -> Optional[dict]:
        """
        Process a detected whale trade and decide whether to copy
        """
        # Validation checks
        if not self.kill_switch.is_active:
            logger.warning("Kill switch active - skipping trade")
            return None

        if signal.whale_address.lower() not in self.tracked_whales:
            return None

        # Calculate position size
        my_balance = await self.get_available_balance()
        whale_balance = self.config.get('whale_balances', {}).get(
            signal.whale_address, 100000  # Default estimate
        )

        my_size = calculate_copy_size(
            signal.amount,
            whale_balance,
            my_balance
        )

        if my_size == 0:
            logger.info(f"Trade too small to copy: ${signal.amount:.2f}")
            return None

        # Check position limits
        current_exposure = sum(p['size'] for p in self.positions.values())
        if current_exposure + my_size > self.config['max_total_exposure']:
            logger.warning("Position limit exceeded - skipping")
            return None

        # Execute copy trade
        logger.info(f"Copying whale trade: {signal.side} ${my_size:.2f} on {signal.market_id}")

        try:
            result = await self.execute_trade(
                market_id=signal.market_id,
                side=signal.side,
                size=my_size,
                price=signal.price
            )

            # Track position
            self.positions[signal.market_id] = {
                'size': my_size,
                'entry_price': signal.price,
                'whale_signal': signal.whale_address
            }

            return result

        except Exception as e:
            logger.error(f"Trade execution failed: {e}")
            return None

    async def execute_trade(self, market_id, side, size, price) -> dict:
        """
        Execute trade using raw transaction signing
        """
        # Build transaction (simplified - use actual CLOB contract)
        nonce = self.w3.eth.get_transaction_count(self.account.address)
        gas_price = self.w3.eth.gas_price

        # ... transaction building logic ...

        return {"status": "executed", "size": size}

    async def get_available_balance(self) -> float:
        """Get available USDC balance on Polymarket"""
        # Implementation depends on Polymarket API
        return 70.0  # Placeholder
```

---

## Monitoring & Alerts

### Telegram Bot Setup

```python
import requests

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

def send_telegram_alert(message: str, priority: str = "normal"):
    """
    Send alert to Telegram
    priority: "low", "normal", "high", "critical"
    """
    emoji = {
        "low": "",
        "normal": "",
        "high": "",
        "critical": ""
    }

    formatted = f"{emoji.get(priority, '')} {message}"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": formatted,
        "parse_mode": "HTML"
    }

    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram alert failed: {e}")

# Alert templates
def alert_trade_executed(whale, market, side, size, price):
    send_telegram_alert(
        f"<b>COPY TRADE</b>\n"
        f"Whale: {whale[:10]}...\n"
        f"Market: {market[:30]}\n"
        f"Side: {side}\n"
        f"Size: ${size:.2f}\n"
        f"Price: {price:.3f}",
        priority="normal"
    )

def alert_kill_switch(reason):
    send_telegram_alert(
        f"<b>KILL SWITCH TRIGGERED</b>\n"
        f"Reason: {reason}\n"
        f"Action: All trading paused",
        priority="critical"
    )
```

---

## Expected Performance

### Benchmarks (from analyses)

| Metric | Conservative | Average | Optimistic |
|--------|--------------|---------|------------|
| Daily Trades | 2-5 | 5-10 | 10-20 |
| Win Rate | 55% | 62% | 70% |
| Avg Profit/Trade | $0.10 | $0.25 | $0.50 |
| Daily Return | $0.20 | $0.80 | $2.00 |
| Monthly Return | $6 | $24 | $60 |
| Monthly ROI | 8.5% | 34% | 85% |

### Realistic Expectations for $70 Capital

**Month 1 (Learning):**
- Focus on paper trading
- Test whale selection
- Tune position sizing
- Expected: Break-even or small loss

**Month 2-3 (Validation):**
- Live trading with small sizes
- Refine kill switch parameters
- Build confidence in system
- Expected: $5-20 profit/month

**Month 4+ (Scaling):**
- Increase position sizes
- Add more whales
- Compound profits
- Expected: $15-50 profit/month

---

## Common Pitfalls

### 1. Copying Closes as Opens

**Problem:** Whale sells existing position, you interpret as "short signal"
**Solution:** Track whale's existing positions before copying

```python
def is_opening_position(whale, market, side):
    """Check if whale is opening or closing"""
    existing = get_whale_position(whale, market)

    if existing is None:
        return True  # New position

    if existing['side'] == side:
        return True  # Adding to position

    return False  # Closing position - don't copy!
```

### 2. Gas Eating Profits

**Problem:** $0.50 profit, $0.30 gas cost = $0.20 actual
**Solution:** Minimum profit threshold

```python
def is_profitable_after_gas(expected_profit, current_gas_gwei):
    gas_cost_usd = estimate_gas_cost(current_gas_gwei)
    min_profit = gas_cost_usd * 2  # Require 2x gas as profit
    return expected_profit > min_profit
```

### 3. Liquidity Exhaustion

**Problem:** Whale buys $10K, you try to buy $10, price moved
**Solution:** Use limit orders, accept partial fills

### 4. Whale Goes Inactive

**Problem:** Tracked whale stops trading, bot sits idle
**Solution:** Monitor activity, rotate whale list monthly

---

## Checklist Before Going Live

- [ ] 3-5 whales selected with proven track records
- [ ] Paper trading ran for 48+ hours successfully
- [ ] Kill switch tested (manually trigger conditions)
- [ ] Telegram alerts working
- [ ] Position sizing verified with test trades
- [ ] Gas estimation accurate
- [ ] Whale activity monitored (all still active)
- [ ] Exit strategy defined for each scenario

---

*Next: [02_CROSS_PLATFORM_ARBITRAGE_GUIDE.md](02_CROSS_PLATFORM_ARBITRAGE_GUIDE.md)*
