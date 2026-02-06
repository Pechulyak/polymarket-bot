# Polymarket Bot Development Kit

**Production-ready patterns for building a $100 capital Polymarket trading bot**

*Consolidated from analysis of 9 arbitrage bot repositories*

---

## Overview

This development kit provides everything you need to build a hybrid trading bot for Polymarket with $100 starting capital. The recommended strategy combines:

- **Copy Trading (70% capital):** Follow profitable whale addresses
- **Cross-Platform Arbitrage (30% capital):** Exploit price differences between Polymarket and Manifold

## Key Insights

| Finding | Impact |
|---------|--------|
| Bundle arbitrage DEAD | 3.15% fee kills profitability |
| Copy Trading = Winner | 8/10 viability for $100 |
| WebSocket > REST | 75-3000x faster |
| Raw TX signing | 5-10x faster than REST API |

## Quick Links

| Document | Description |
|----------|-------------|
| [00_QUICK_START.md](00_QUICK_START.md) | 5-minute setup guide |
| [01_COPY_TRADING_GUIDE.md](01_COPY_TRADING_GUIDE.md) | Primary strategy (whale following) |
| [02_CROSS_PLATFORM_ARBITRAGE_GUIDE.md](02_CROSS_PLATFORM_ARBITRAGE_GUIDE.md) | Secondary strategy (Poly + Manifold) |
| [03_ARCHITECTURE_BLUEPRINT.md](03_ARCHITECTURE_BLUEPRINT.md) | System design |
| [04_CODE_LIBRARY/](04_CODE_LIBRARY/) | Ready-to-use Python modules |
| [05_PERFORMANCE_DATA.md](05_PERFORMANCE_DATA.md) | Benchmarks and metrics |
| [06_COMPLIANCE_CHECKLIST.md](06_COMPLIANCE_CHECKLIST.md) | ToS safety guide |
| [07_DEPLOYMENT_GUIDE.md](07_DEPLOYMENT_GUIDE.md) | Production deployment |

## Code Library

Ready-to-use Python modules in [04_CODE_LIBRARY/](04_CODE_LIBRARY/):

```
04_CODE_LIBRARY/
├── __init__.py
├── polymarket_client.py      # Polymarket CLOB API wrapper
├── websocket_manager.py      # Real-time data feeds
├── copy_trading_engine.py    # Whale following logic
├── arbitrage_detector.py     # Cross-platform scanner
├── risk_manager.py           # Unified risk control
├── order_executor.py         # REST + Raw TX execution
└── telegram_alerts.py        # Monitoring & alerts
```

## Expected Performance

| Metric | Copy Trading | Arbitrage | Combined |
|--------|-------------|-----------|----------|
| Daily Opportunities | 5-15 | 1-3 | 6-18 |
| Avg Profit/Trade | $0.10-0.40 | $2-10 | - |
| Daily Return | $0.50-2 | $0-10 | $0.50-12 |
| Win Rate | 60-70% | 80-90% | 65-75% |

## Technology Stack

| Layer | Recommended |
|-------|-------------|
| Language | Python 3.11+ |
| WebSocket | websockets |
| Blockchain | web3.py 6.x |
| Database | SQLite + Redis |
| Monitoring | Telegram Bot |

## Source Repositories

This kit consolidates patterns from 9 analyzed repositories:

| Repository | Strategy | Viability |
|------------|----------|-----------|
| crypmancer/polymarket-arbitrage-copy-bot | Copy Trading | 8/10 |
| hodlwarden/polymarket-arbitrage-copy-bot | Advanced Copy | 8/10 |
| realfishsam/prediction-market-arbitrage-bot | Cross-Platform | 8/10 |
| coleschaffer/Gabagool | Cross-Platform + UI | 6/10 |
| Jonmaa/btc-polymarket-bot | TA Prediction | 5/10 |
| cakaroni/polymarket-arbitrage-bot-btc-eth-15m | Time-Window | 3/10 |
| apemoonspin/polymarket-arbitrage-trading-bot | Bundle (deprecated) | 2/10 |
| CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot | Cross-Platform (Kalshi) | 2/10 |
| 0xRustElite1111/polymarket-arbitrage-trading-bot | HFT (Rust) | 2/10 |

## Getting Started

```bash
# 1. Read the quick start guide
open 00_QUICK_START.md

# 2. Set up your environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# 3. Configure your .env
cp .env.example .env
# Edit with your private key and RPC URL

# 4. Start paper trading
python main.py --mode=paper
```

## Requirements

- Python 3.11+
- Polymarket account with funded wallet
- (Optional) Manifold account for cross-platform arb
- (Production) VPS with <50ms latency to Polygon

## Cost Summary

| Item | Development | Production |
|------|-------------|------------|
| VPS | $0 (local) | $4-6/month |
| RPC | Free tier | Free tier |
| Capital | $100 | $100 |
| **Monthly** | **$100 once** | **$4-6** |

## Safety Notes

- Start with paper trading
- Use a fresh wallet for bot trading
- Never commit private keys to git
- Implement kill switches
- Monitor actively during early operation

## Related Resources

| Resource | Description |
|----------|-------------|
| [BEST_PRACTICES_CONSOLIDATED.md](../BEST_PRACTICES_CONSOLIDATED.md) | Full consolidated analysis from 9 repositories |
| [PARENT_PROJECT_HANDOFF.md](../PARENT_PROJECT_HANDOFF.md) | Implementation roadmap for parent project |
| [Level 2 Analyses](../level2_analysis/) | Individual deep-dive analyses |
| [GitHub Repository](https://github.com/Pechulyak/polymarket-research) | Source repository |

## License

This documentation is provided for educational purposes. Use at your own risk. Trading involves risk of financial loss.

---

*Generated: 2026-02-03*
*Source: Polymarket Research Project - Level 2 Analysis*
*Repository: https://github.com/Pechulyak/polymarket-research*
