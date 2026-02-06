# Compliance Checklist - ToS Safety Guide

*Safe patterns and anti-patterns for Polymarket trading bots*

---

## Quick Reference

| Activity | Status | Notes |
|----------|--------|-------|
| Copy trading (public data) | ✅ SAFE | Following blockchain txs |
| Cross-platform arbitrage | ✅ SAFE | Different platforms, same event |
| Limit order placement | ✅ SAFE | Standard trading |
| Price discovery arb | ✅ SAFE | Market efficiency |
| API rate limiting respect | ✅ REQUIRED | Must implement |
| Wash trading | ❌ PROHIBITED | Trading with yourself |
| Market manipulation | ❌ PROHIBITED | Coordinated schemes |
| Multiple accounts | ❌ PROHIBITED | Circumventing limits |
| Front-running (non-public) | ❌ PROHIBITED | Insider information |
| Excessive API abuse | ❌ RISKY | Can result in bans |

---

## Safe Patterns

### 1. Copy Trading (Whale Following)

**Status:** ✅ ALLOWED

**Why Safe:**
- Uses public blockchain data
- Anyone can observe transactions
- No different from manual watching
- Standard market behavior

**Best Practices:**
```python
# GOOD: Following public blockchain transactions
async def monitor_whale(address):
    # Watch confirmed transactions (public)
    txs = await get_address_transactions(address)
    for tx in txs:
        if is_polymarket_trade(tx):
            await analyze_and_copy(tx)

# GOOD: Using Polygonscan/Dune data
whale_addresses = fetch_from_dune_analytics()
```

**Avoid:**
- Don't claim to have "insider" access
- Don't coordinate with whales
- Don't impersonate whale addresses

---

### 2. Cross-Platform Arbitrage

**Status:** ✅ ALLOWED

**Why Safe:**
- Trading on different platforms
- Price discovery is beneficial
- No manipulation of single platform
- Standard financial practice

**Best Practices:**
```python
# GOOD: Independent platform operations
poly_price = await polymarket.get_price(market)
manifold_price = await manifold.get_price(market)

if significant_spread(poly_price, manifold_price):
    # Trade on both platforms independently
    await polymarket.buy(...)
    await manifold.sell(...)
```

**Considerations:**
- Each platform has its own ToS
- Kalshi requires KYC (US only)
- Manifold terms are more permissive
- Keep records of all trades

---

### 3. Limit Order Market Making

**Status:** ✅ ALLOWED

**Why Safe:**
- Provides liquidity
- Standard CLOB behavior
- Benefits market efficiency
- No deception involved

**Best Practices:**
```python
# GOOD: Two-sided quoting
async def provide_liquidity(market):
    mid_price = await get_mid_price(market)
    spread = 0.02  # 2% spread

    # Place orders on both sides
    await place_limit_order(side="BUY", price=mid_price - spread/2)
    await place_limit_order(side="SELL", price=mid_price + spread/2)
```

---

### 4. API Usage (With Rate Limiting)

**Status:** ✅ REQUIRED

**Why Important:**
- Protects platform infrastructure
- Shows good faith
- Prevents bans
- Required by ToS

**Implementation:**
```python
# GOOD: Rate limiting implementation
from asyncio import Semaphore, sleep

class RateLimiter:
    def __init__(self, requests_per_second=10):
        self.semaphore = Semaphore(requests_per_second)
        self.delay = 1.0 / requests_per_second

    async def acquire(self):
        await self.semaphore.acquire()
        asyncio.create_task(self._release_after_delay())

    async def _release_after_delay(self):
        await sleep(self.delay)
        self.semaphore.release()

# Usage
limiter = RateLimiter(requests_per_second=10)

async def safe_api_call(endpoint):
    await limiter.acquire()
    return await api.call(endpoint)
```

**Polymarket Rate Limits (estimated):**

| Endpoint Type | Limit | Notes |
|---------------|-------|-------|
| Public market data | 60/min | Orderbooks, prices |
| Authenticated | 30/min | Orders, balances |
| WebSocket | 1 connection | With subscriptions |

---

## Prohibited Activities

### 1. Wash Trading

**Status:** ❌ PROHIBITED

**What It Is:**
Trading with yourself to artificially inflate volume or manipulate prices.

**Examples:**
```python
# BAD: Trading between your own accounts
account_a.sell(market, price=0.50)
account_b.buy(market, price=0.50)  # Same person!

# BAD: Circular trading to inflate volume
for i in range(100):
    buy(market)
    sell(market)  # Fake volume
```

**Why Prohibited:**
- Deceives other traders
- Manipulates market metrics
- Violates securities principles
- Explicitly banned in ToS

---

### 2. Market Manipulation

**Status:** ❌ PROHIBITED

**Types:**
- **Pump and dump:** Coordinated buying then selling
- **Spoofing:** Fake orders to move price
- **Layering:** Multiple fake orders to create illusion
- **Coordinated trading:** Group manipulation

**Examples:**
```python
# BAD: Spoofing (placing orders you intend to cancel)
await place_large_buy_order(price=0.60)  # Fake demand
# Price moves up
await cancel_order()  # Never intended to fill
await sell(price=0.61)  # Profit from manipulation

# BAD: Pump and dump coordination
discord_message("Everyone buy NOW!")
await buy_large_position()
# Wait for others to buy
await sell_all()  # Dump on followers
```

---

### 3. Multiple Accounts / Bot Swarms

**Status:** ❌ PROHIBITED

**What It Is:**
Operating multiple accounts to circumvent limits or gain unfair advantage.

**Why Prohibited:**
- Circumvents position limits
- Enables wash trading
- Unfair advantage
- ToS violation

**Detection Patterns:**
- Same IP address
- Same wallet funding source
- Coordinated trading patterns
- Similar timing patterns

---

### 4. Front-Running (Non-Public Information)

**Status:** ❌ PROHIBITED (with caveats)

**Distinction:**

| Type | Status | Description |
|------|--------|-------------|
| Public mempool | ⚠️ Gray area | Watching pending txs |
| Private information | ❌ Prohibited | Insider data |
| MEV extraction | ⚠️ Gray area | Blockchain-level |

**Safe Approach:**
```python
# ACCEPTABLE: Watching public pending transactions
async def watch_mempool():
    # This is public blockchain data
    pending_txs = await get_pending_transactions()
    # React to what you see

# PROHIBITED: Using private API access
async def insider_trading():
    # If you have special access to order flow...
    private_orders = await internal_api.get_pending_orders()
    await front_run(private_orders)  # ILLEGAL
```

---

## Private Key Safety

### Required Practices

```python
# ✅ GOOD: Environment variables
import os
PRIVATE_KEY = os.environ.get("POLY_PRIVATE_KEY")

# ✅ GOOD: Encrypted keystore
from eth_account import Account
with open("keystore.json") as f:
    keystore = json.load(f)
account = Account.decrypt(keystore, password)

# ✅ GOOD: Hardware wallet (for large amounts)
from web3 import Web3
w3 = Web3()
# Use hardware wallet for signing

# ❌ BAD: Hardcoded keys
PRIVATE_KEY = "0x1234567890..."  # NEVER DO THIS

# ❌ BAD: Keys in git
# .env file committed to repository

# ❌ BAD: Keys in logs
logger.info(f"Using key: {private_key}")  # NEVER LOG KEYS
```

### .gitignore Requirements

```gitignore
# REQUIRED entries
.env
.env.*
*.key
*_key.json
keystore.json
credentials.json
secrets/
config/local.py
```

---

## Legal Considerations

### Jurisdiction Issues

| Region | Polymarket Status | Notes |
|--------|-------------------|-------|
| USA | ⚠️ Restricted | Officially blocked, VPN usage risky |
| EU | ✅ Generally OK | Check local gambling laws |
| UK | ✅ Generally OK | Betting regulations apply |
| Asia | Varies | Country-specific |

### Tax Considerations

- **Crypto trading** is taxable in most jurisdictions
- Keep records of all trades
- Report profits appropriately
- Consult local tax advisor

### Recommended Record Keeping

```python
# Trade logging for tax/compliance
def log_trade(trade_data):
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "platform": "polymarket",
        "market": trade_data["market"],
        "side": trade_data["side"],
        "size_usd": trade_data["size"],
        "price": trade_data["price"],
        "tx_hash": trade_data["tx_hash"],
        "fees_usd": trade_data["fees"]
    }

    # Save to persistent storage
    save_to_database(record)
    save_to_csv_backup(record)
```

---

## Platform-Specific Notes

### Polymarket

**Key ToS Points:**
- No US users (officially)
- No wash trading
- No market manipulation
- Rate limits must be respected
- Single account per person

**API Fair Use:**
- Respect rate limits
- Don't hammer endpoints
- Use WebSocket for real-time data
- Cache when possible

### Manifold

**Key ToS Points:**
- More permissive
- Play money and real money tiers
- Bot usage generally allowed
- API is well-documented

### Kalshi

**Key ToS Points:**
- CFTC regulated
- US-only (with KYC)
- Stricter compliance
- Larger minimums

---

## Compliance Checklist

### Before Going Live

- [ ] Single account only
- [ ] No wash trading patterns
- [ ] Rate limiting implemented
- [ ] Private keys secured
- [ ] .gitignore configured
- [ ] Trade logging enabled
- [ ] Jurisdiction verified
- [ ] ToS reviewed

### Ongoing Monitoring

- [ ] Regular ToS review (monthly)
- [ ] Rate limit compliance verified
- [ ] No suspicious pattern flags
- [ ] Clean IP reputation
- [ ] Trade records maintained

### If Contacted by Platform

1. Respond promptly
2. Be honest about bot usage
3. Explain legitimate purpose
4. Provide requested information
5. Cease activity if required

---

## Emergency Procedures

### If Account Flagged

```python
# Immediate actions
async def emergency_shutdown():
    # 1. Stop all trading
    await cancel_all_orders()

    # 2. Document everything
    save_all_logs()
    export_trade_history()

    # 3. Preserve funds if possible
    # (Don't attempt withdrawals if flagged)

    # 4. Contact support
    # Be honest and cooperative
```

### Contact Information

- Polymarket: support@polymarket.com
- Polymarket Discord: [Official server]
- Manifold: support@manifold.markets

---

## Summary

**DO:**
- Follow public blockchain data
- Trade across platforms
- Provide liquidity
- Respect rate limits
- Keep records
- Secure keys

**DON'T:**
- Wash trade
- Manipulate markets
- Use multiple accounts
- Abuse APIs
- Share keys
- Ignore ToS updates

---

*Disclaimer: This is not legal advice. Consult appropriate professionals for jurisdiction-specific guidance.*

*Last updated: 2026-02-03*
