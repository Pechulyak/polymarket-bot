# AGENT CONTEXT - Polymarket Research Project

## PROJECT OVERVIEW
**Goal:** Automated research pipeline for analyzing Polymarket trading bot repositories with focus on arbitrage strategies. This research feeds into a parent project: developing a production-ready arbitrage bot for $100 capital.

**Timeline:** 1 week research phase (completed in 3 days)
**Current Phase:** ✅ COMPLETED - Deliverable Ready for Parent Project

## PROJECT STATUS

| Metric | Value |
|--------|-------|
| Repositories Analyzed | 107 |
| Level 2 Deep Dives | 9 |
| Bot Development Kit | 21 files, 9,093 lines |
| Research Duration | 3 days (Feb 1-2, 2026) |
| Status | Ready for Implementation |

## PROJECT STRUCTURE
```
polymarket-research/
├── data/
│   ├── exports/          # 107 analyzed repos (JSON)
│   ├── repos_list.txt    # Full list (87 repos)
│   └── level2_priority_list.txt  # Top 10 arbitrage bots
├── docs/
│   ├── bot_development_kit/      # MAIN DELIVERABLE
│   │   ├── 00_QUICK_START.md
│   │   ├── 01_COPY_TRADING_GUIDE.md
│   │   ├── 02_CROSS_PLATFORM_ARBITRAGE_GUIDE.md
│   │   ├── 03_ARCHITECTURE_BLUEPRINT.md
│   │   ├── 04_CODE_LIBRARY/      # 7 Python modules
│   │   ├── 05_PERFORMANCE_DATA.md
│   │   ├── 06_COMPLIANCE_CHECKLIST.md
│   │   └── 07_DEPLOYMENT_GUIDE.md
│   ├── level2_analysis/
│   │   ├── arbitrage/
│   │   ├── code_snippets/
│   │   └── summaries/INDEX.md
│   ├── chat_contexts/
│   ├── MASTER_CHANGELOG.md
│   ├── PARENT_PROJECT_HANDOFF.md
│   └── AGENT_CONTEXT.md  # THIS FILE
├── src/
│   ├── analysis/level1_analyzer.py
│   └── storage/sheets_client.py
├── scripts/
│   ├── analyze_repo.py
│   ├── batch_analyze_interactive.py
│   └── prioritize_arbitrage_bots.py
└── .env  # GitHub token, Google credentials
```

## COMPLETED MILESTONES
✅ M1: Foundation & Manual Analysis (3 repos analyzed)
✅ M2: Batch Processing (107 repos, 96 in Google Sheets)
✅ M3: Level 2 Deep Dive + Bot Development Kit (9 analyses, 21 files)

## CRITICAL FINDINGS

**CRITICAL PIVOT (from Level 2 analyses):**
❌ Bundle arbitrage DEAD (3.15% Polymarket fee kills profitability)
✅ Copy Trading = WINNER for $100 capital (8/10 viability)
  - Winner: crypmancer/polymarket-arbitrage-copy-bot
  - Advanced: hodlwarden/polymarket-arbitrage-copy-bot
⚡ WebSocket > REST by 75-3000x (critical competitive advantage)
🚀 Raw tx signing 5-10x faster than REST API

**Validated Strategy Priority:**
1. Copy Trading (beginner-friendly, 8/10 viability) - PRIMARY
2. Cross-Platform Arbitrage (advanced, 8/10) - SECONDARY
3. Bundle Arbitrage (DEPRECATED - unprofitable post-fees)

**Capital Allocation ($100):**
- Copy Trading: $70 (70%) - stable base income
- Cross-Platform Arb: $25 (25%) - opportunistic upside
- Gas Reserve: $5 (5%) - Polygon costs

**Expected Performance:**
- Conservative: $15-60/month (15-60% return)
- Realistic: $30-100/month (30-100% return)
- Optimistic: $60-360/month with optimal execution

## LEVEL 2 ANALYSES COMPLETED

| # | Repository | Strategy | Viability |
|---|------------|----------|-----------|
| 1 | crypmancer/polymarket-arbitrage-copy-bot | Copy Trading | 8/10 |
| 2 | hodlwarden/polymarket-arbitrage-copy-bot | Advanced Copy | 8/10 |
| 3 | realfishsam/prediction-market-arbitrage-bot | Cross-Platform | 8/10 |
| 4 | coleschaffer/Gabagool | Cross-Platform + UI | 6/10 |
| 5 | Jonmaa/btc-polymarket-bot | TA Prediction | 5/10 |
| 6 | cakaroni/polymarket-arbitrage-bot-btc-eth-15m | Time-Window | 3/10 |
| 7 | apemoonspin/polymarket-arbitrage-trading-bot | Bundle | 2/10 |
| 8 | CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot | Kalshi | 2/10 |
| 9 | 0xRustElite1111/polymarket-arbitrage-trading-bot | HFT (Rust) | 2/10 |

## BOT DEVELOPMENT KIT

**Location:** `docs/bot_development_kit/`

### Guides (7 documents)
1. `00_QUICK_START.md` - 5-minute setup
2. `01_COPY_TRADING_GUIDE.md` - Primary strategy
3. `02_CROSS_PLATFORM_ARBITRAGE_GUIDE.md` - Secondary strategy
4. `03_ARCHITECTURE_BLUEPRINT.md` - System design
5. `05_PERFORMANCE_DATA.md` - Benchmarks
6. `06_COMPLIANCE_CHECKLIST.md` - ToS safety
7. `07_DEPLOYMENT_GUIDE.md` - Production setup

### Code Library (7 modules)
```
04_CODE_LIBRARY/
├── polymarket_client.py      # CLOB API wrapper
├── websocket_manager.py      # Real-time feeds
├── copy_trading_engine.py    # Whale following
├── arbitrage_detector.py     # Cross-platform scanner
├── risk_manager.py           # Kill switch + limits
├── order_executor.py         # REST + Raw TX
└── telegram_alerts.py        # Monitoring
```

## GOOGLE INTEGRATION
**Sheets:** https://docs.google.com/spreadsheets/d/1vdQvFqVZYaKU3BY3A2zq9Z2NdHy9sM0djr93Srwyy8s
- 15 columns: Name, URL, Stars, Strategies, Tech Tags, Level 2 Priority
- 96 repositories populated

**Credentials:**
- GitHub Token: .env (GITHUB_TOKEN)
- Google Service Account: config/google_service_account.json

## CRITICAL CONSTRAINTS (for Parent Project)
- **Capital:** $100 starting bankroll
- **Strategies:** Copy Trading primary, cross-platform secondary
- **Performance:** WebSocket mandatory (REST too slow)
- **Compliance:** ToS-safe patterns only (see 06_COMPLIANCE_CHECKLIST.md)

## NEXT PHASE: Parent Project (Bot Implementation)

See `docs/PARENT_PROJECT_HANDOFF.md` for complete implementation roadmap.

**Timeline:**
- Week 1: Copy Trading MVP (paper trading)
- Week 2: Production hardening + live deployment
- Week 3: Arbitrage integration
- Week 4: Optimization & scaling

## GITHUB REPOSITORY
https://github.com/Pechulyak/polymarket-research

---

## USAGE FOR NEW CHATS
Every new Claude Code task should begin:

"Navigate to D:\projects\polymarket-research and read docs/AGENT_CONTEXT.md"

Then provide the specific task.

---

*Last updated: 2026-02-03*
*Status: Research Phase Complete*
