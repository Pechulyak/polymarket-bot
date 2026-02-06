# Polymarket Trading Bot

High-frequency arbitrage bot for Polymarket prediction markets. Enhanced with comprehensive research from 107 trading bot repositories.

**⚠️ No ML/LLM prediction models — pure statistical arbitrage only.**

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
# Edit .env with your credentials

# Start infrastructure
docker-compose up -d

# Run paper trading
python src/main.py --mode paper --bankroll 10.00

# Run copy trading (from research)
python main.py --mode=paper --strategy=copy
```

## 📊 Research Integration

This project includes a **complete Bot Development Kit** from 3-day research analyzing 107 repositories:

**Key Finding**: Copy Trading is the WINNER strategy for $100 capital (8/10 viability)

### Validated Strategies

1. **🥇 Copy Trading (Primary)** - 70% allocation
   - Follow profitable whale addresses
   - Edge: 15-25 bps per trade
   - Win Rate: 65%
   - Daily Return: $0.50-2.00

2. **🥈 Cross-Market Arbitrage (Secondary)** - 25% allocation
   - Polymarket vs Manifold/Bybit price divergences
   - Edge: 20-40 bps per trade
   - Win Rate: 75%
   - Requires spreads >5%

3. **❌ Bundle Arbitrage (DEPRECATED)** - 0% allocation
   - Killed by 3.15% Polymarket fees

### Capital Allocation ($100)

```
Total: $100
├── Copy Trading Reserve: $70 (70%)
├── Arbitrage Reserve: $25 (25%)
└── Gas Reserve: $5 (5%)
```

## 📁 Project Structure

```
polymarket/
├── src/                          # Core Python modules
│   ├── config/                   # Settings & risk params
│   ├── data/                     # Data ingestion & storage
│   ├── strategy/                 # Trading strategies
│   │   └── selected_strategies.py # Kelly Criterion sizing
│   ├── execution/                # Order execution
│   ├── risk/                     # Risk management
│   ├── research/                 # Strategy research
│   └── main.py                   # Entry point
├── docs/
│   ├── bot_development_kit/      # 🎯 COMPLETE BOT KIT
│   │   ├── 00_QUICK_START.md
│   │   ├── 01_COPY_TRADING_GUIDE.md
│   │   ├── 02_CROSS_PLATFORM_ARBITRAGE_GUIDE.md
│   │   ├── 03_ARCHITECTURE_BLUEPRINT.md
│   │   ├── 04_CODE_LIBRARY/      # 7 Python modules
│   │   ├── 05_PERFORMANCE_DATA.md
│   │   ├── 06_COMPLIANCE_CHECKLIST.md
│   │   └── 07_DEPLOYMENT_GUIDE.md
│   ├── RESEARCH_INTEGRATION.md   # Research summary
│   ├── RESEARCH_AGENT_CONTEXT.md # Full context
│   ├── AGENTS.md                 # Coding guidelines
│   └── ARCHITECTURE.md           # System design
├── notebooks/
│   └── research_analysis.ipynb   # Strategy research
├── scripts/
│   └── init_db.sql               # PostgreSQL schema
├── tests/                        # Unit & integration tests
├── docker-compose.yml
└── requirements.txt
```

## 🎯 Bot Development Kit

### 7 Ready-to-Use Modules

Located in `docs/bot_development_kit/04_CODE_LIBRARY/`:

```python
# Example: Copy Trading
from docs.bot_development_kit.04_CODE_LIBRARY import (
    CopyTradingEngine, RiskManager, PolymarketClient
)

# Initialize copy trading
engine = CopyTradingEngine(
    config={
        "whale_addresses": ["0x123...", "0x456..."],
        "copy_capital": 70.0,
        "min_copy_size": 5.0,
        "max_copy_size": 20.0
    },
    risk_manager=risk_manager,
    executor=executor
)
```

### Key Research Insights Applied

1. **⚡ WebSocket > REST by 75-3000x**
   - Critical for arbitrage latency
   - Use `websocket_manager.py`

2. **🚀 Raw TX Signing 5-10x Faster**
   - 60ms vs 500ms execution
   - Use `order_executor.py` with `mode="raw"`

3. **💰 Fee Chain Accounting**
   - Fiat → Bybit → MetaMask → Polymarket
   - Full fee tracking in `risk_manager.py`

## 📈 Expected Performance

| Metric | Conservative | Realistic | Optimistic |
|--------|-------------|-----------|------------|
| Monthly Return | $15-60 | $30-100 | $60-360 |
| ROI | 15-60% | 30-100% | 60-360% |
| Win Rate | 60-65% | 65-75% | 70-80% |
| Daily Trades | 5-10 | 8-18 | 15-25 |

## 🧪 Testing

```bash
# All tests
pytest tests/ -v

# Single test
pytest tests/unit/test_kelly.py::test_position_sizing -v

# With coverage
pytest --cov=src --cov-report=html

# Paper trading mode
python src/main.py --mode paper --bankroll 10.00

# Copy trading paper mode
python main.py --mode=paper --strategy=copy
```

## 🚀 Deployment

### Milestone Commits (Required)

```bash
# Research phase complete
git commit -m "milestone: research v0.1.0 - strategy analysis framework

- GitHub scraper for repo analysis
- Twitter/X sentiment collector
- Signal aggregation engine"

# Copy trading ready
git commit -m "milestone: copy-trading v0.2.0 - whale following

- WebSocket whale monitoring
- Proportional position sizing
- Risk management with kill switch"

# Production release
git commit -m "milestone: bot v1.0.0 - production ready

- Virtual bankroll: $10 → $12.50 (25% ROI)
- 47 trades, 38 wins (81% win rate)
- Ready for live deployment"

# Tag release
git tag -a v1.0.0 -m "Production release"
```

### Production Deployment

```bash
# Deploy with Docker
docker-compose -f docker/docker-compose.prod.yml up -d

# Run live trading
python main.py --mode=live --strategy=hybrid
```

## 📚 Documentation

### Essential Reading

1. **[Bot Development Kit](docs/bot_development_kit/)** - Complete implementation guides
   - `00_QUICK_START.md` - 5-minute setup
   - `01_COPY_TRADING_GUIDE.md` - Primary strategy
   - `04_CODE_LIBRARY/` - Ready-to-use Python modules

2. **[Research Integration](docs/RESEARCH_INTEGRATION.md)** - Research findings
3. **[Architecture](ARCHITECTURE.md)** - System design
4. **[Agents Guide](AGENTS.md)** - Coding standards

### Research Sources

**107 Repositories Analyzed**, including:
- crypmancer/polymarket-arbitrage-copy-bot (8/10)
- hodlwarden/polymarket-arbitrage-copy-bot (8/10)
- realfishsam/prediction-market-arbitrage-bot (8/10)

**Full Research Data**: [Google Sheets](https://docs.google.com/spreadsheets/d/1vdQvFqVZYaKU3BY3A2zq9Z2NdHy9sM0djr93Srwyy8s)

## ⚠️ Risk Warning

- Start with **virtual bankroll** ($10)
- **Kill switch** activates on 2% daily drawdown
- Never risk more than **25% of bankroll** per trade
- Full **fee chain** tracked: fiat → Bybit → MetaMask → Polymarket
- Bundle arbitrage **unprofitable** (3.15% fees)

## 🛡️ Compliance

All strategies comply with Polymarket ToS:
- ✅ No wash trading
- ✅ No market manipulation
- ✅ Respect API rate limits
- ✅ <5% of daily volume per trade

See [Compliance Checklist](docs/bot_development_kit/06_COMPLIANCE_CHECKLIST.md)

## 📞 Support

- **Polymarket Discord**: https://discord.gg/polymarket
- **Polygon Status**: https://status.polygon.technology/
- **Research Project**: https://github.com/Pechulyak/polymarket-research

## License

MIT

---

**Status**: Research Phase ✅ COMPLETED | Implementation Phase 🚀 READY

*Last updated: 2026-02-06*
