# Quick Start - $100 Polymarket Hybrid Bot

## Strategy Overview

**Hybrid approach for $100 capital:**
- **Primary (70% capital):** Copy Trading - Stable, predictable returns
- **Secondary (30% capital):** Cross-Platform Arbitrage - Opportunistic high-yield

**Why Hybrid?**
- Copy trading provides base income ($0.50-2/day)
- Arbitrage captures rare high-profit opportunities ($2-10/trade)
- Risk diversification across strategies

---

## Capital Allocation

```
Total: $100
├── Copy Trading Reserve: $70
│   ├── Active positions: $50
│   └── Buffer: $20
├── Arbitrage Reserve: $25
└── Gas Reserve (Polygon): $5
```

---

## Expected Performance

| Metric | Copy Trading | Arbitrage | Combined |
|--------|-------------|-----------|----------|
| Daily Opportunities | 5-15 | 1-3 | 6-18 |
| Avg Profit/Trade | $0.10-0.40 | $2-10 | - |
| Daily Return | $0.50-2 | $0-10 | $0.50-12 |
| Risk Level | Low | Medium | Low-Med |
| Win Rate | 60-70% | 80-90% | 65-75% |

---

## Prerequisites

- **Python 3.11+** (recommended) OR Node.js 18+
- **Polymarket account** with funded wallet ($100 USDC)
- **(Optional)** Manifold account for cross-platform arb
- **(Production)** VPS with <50ms latency to Polygon RPC

---

## 5-Minute Local Setup

```bash
# 1. Clone your bot repo
git clone [your-bot-repo]
cd polymarket-bot

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate  # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your PRIVATE_KEY and RPC_URL

# 5. Verify setup
python -m pytest tests/

# 6. Start in paper trading mode
python main.py --mode=paper
```

---

## Architecture

```
┌─────────────────────────────────────────┐
│         WebSocket Manager               │
│  (Polymarket + Manifold real-time)      │
└─────────────┬───────────────────────────┘
              │
    ┌─────────┴─────────┐
    │                   │
    ▼                   ▼
┌─────────────┐   ┌──────────────┐
│ Copy Engine │   │  Arb Engine  │
│  (70% cap)  │   │  (30% cap)   │
└──────┬──────┘   └──────┬───────┘
       │                 │
       └────────┬────────┘
                ▼
       ┌───────────────┐
       │ Risk Manager  │
       │   (Unified)   │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │   Executor    │
       │ (CLOB + Web3) │
       └───────────────┘
```

---

## Key Configuration

```python
# config.py - Essential settings for $100 bot

# Strategy allocation
COPY_TRADING_CAPITAL = 70      # $70 for copy trading
ARBITRAGE_CAPITAL = 25         # $25 for cross-platform
GAS_RESERVE = 5                # $5 for Polygon gas

# Copy Trading Settings
WHALE_ADDRESSES = [
    "0x...",  # Top trader 1 (from Polymarket leaderboard)
    "0x...",  # Top trader 2
    "0x...",  # Top trader 3
]
MIN_COPY_SIZE = 5              # $5 minimum per trade
MAX_COPY_SIZE = 20             # $20 maximum per trade

# Risk Management
MAX_DAILY_LOSS = 10            # $10 daily loss limit (kill switch)
MAX_POSITION_PER_MARKET = 15   # $15 max per market
MAX_CONSECUTIVE_LOSSES = 3     # Stop after 3 losses in a row

# Performance
WEBSOCKET_ENABLED = True       # Critical! 75-3000x faster than REST
RAW_TX_SIGNING = True          # 5-10x faster than REST API
```

---

## Workflow Overview

### Copy Trading (Primary)

1. **Monitor:** WebSocket streams whale addresses for pending/confirmed txs
2. **Decode:** Parse CLOB trade transactions to extract (market, side, size)
3. **Evaluate:** Check if trade passes risk filters
4. **Copy:** Execute proportional trade within 1-2 blocks
5. **Exit:** Follow whale's exit or hit profit target

### Cross-Platform Arbitrage (Secondary)

1. **Monitor:** WebSocket streams from Polymarket + Manifold
2. **Detect:** Compare prices, identify >5% spreads
3. **Validate:** Check liquidity depth on both sides
4. **Execute:** Place concurrent orders on both platforms
5. **Settle:** Wait for market resolution, collect profit

---

## Quick Validation Checklist

Before going live with real money:

- [ ] Paper trading ran for 24+ hours without errors
- [ ] WebSocket reconnection tested (disconnect/reconnect)
- [ ] Kill switch triggers correctly at loss limit
- [ ] Telegram alerts working for trades and errors
- [ ] Gas estimation accurate (check last 10 trades)
- [ ] Whale addresses are still active/profitable

---

## Next Steps

1. **[01_COPY_TRADING_GUIDE.md](01_COPY_TRADING_GUIDE.md)** - Deep dive into primary strategy
2. **[02_CROSS_PLATFORM_ARBITRAGE_GUIDE.md](02_CROSS_PLATFORM_ARBITRAGE_GUIDE.md)** - Secondary strategy details
3. **[03_ARCHITECTURE_BLUEPRINT.md](03_ARCHITECTURE_BLUEPRINT.md)** - Full system design
4. **[04_CODE_LIBRARY/](04_CODE_LIBRARY/)** - Ready-to-use Python modules
5. **[05_PERFORMANCE_DATA.md](05_PERFORMANCE_DATA.md)** - Benchmarks and metrics
6. **[06_COMPLIANCE_CHECKLIST.md](06_COMPLIANCE_CHECKLIST.md)** - ToS safety guide
7. **[07_DEPLOYMENT_GUIDE.md](07_DEPLOYMENT_GUIDE.md)** - Production deployment

---

## Emergency Contacts

- **Polymarket Discord:** https://discord.gg/polymarket
- **Polygon Status:** https://status.polygon.technology/
- **Alchemy Status:** https://status.alchemy.com/

---

*Last updated: 2026-02-03*
*Source: Consolidated from 9 Level 2 repository analyses*
