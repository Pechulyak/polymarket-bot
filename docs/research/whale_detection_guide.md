# Whale Detection Guide - Polymarket

## Executive Summary

Система отслеживания "китов" (крупных трейдеров) на Polymarket для повышения win rate trading bot. Исследование выявило способы получения адресов и критерии quality whale (>60% win rate).

## ПРОБЛЕМА: Как получить адреса китов?

WebSocket НЕ предоставляет адреса трейдеров. Data API требует адрес заранее.

### Решения:
1. **Bitquery** - получить ВСЕ сделки с адресами (рекомендуется)
2. **Polymarket Subgraph** - query all trades
3. **Dune Analytics** - топ трейдеры по объёму
4. **Готовые сервисы** - Polywhaler, PolymarketScan

## Data Sources Overview

| Source | Type | Cost | Real-time | Addresses | Data Quality |
|--------|------|------|-----------|-----------|--------------|
| **Bitquery** | On-chain GraphQL | Free tier | Yes | Yes | High |
| Polymarket Subgraph | On-chain | Free | ~15 min | Limited | High |
| Data API | REST | Free | Yes | No* | High |
| Polywhaler | Web App | Free/Paid | Yes | Yes | High |
| Dune Analytics | SQL | Free | Yes | Yes | Medium |

*Data API: требует адрес для запроса

---

## 1. Bitquery - ПОЛУЧИТЬ ВСЕ СДЕЛКИ С АДРЕСАМИ

### Почему Bitquery:
- Реальные адреса трейдеров из блокчейна
- Real-time данные с Polygon
- Можно фильтровать по size (size > $1000)
- Бесплатный tier доступен

### Smart Contracts
```
CTF Exchange (Current): 0xC5d563A36AE78145C45a50134d48A1215220f80a
CTF Exchange (Legacy): 0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
Main Contract:        0x4d97dcd97ec945f40cf65f87097ace5ea0476045
```

### Query: Получить все сделки с адресами (последние 24ч)
```graphql
{
  EVM(dataset: realtime, network: matic) {
    Events(
      orderBy: {descending: Block_Time}
      where: {
        Block: {Time: {since_relative: {hours_ago: 24}}}
        Log: {Signature: {in: ["OrderFilled"]}}
        LogHeader: {
          Address: {
            in: [
              "0xC5d563A36AE78145C45a50134d48A1215220f80a",
              "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
            ]
          }
        }
      }
      limit: {count: 100}
    ) {
      Block {
        Time
        Number
      }
      Transaction {
        Hash
        Sender  # <-- АДРЕС ТРЕЙДЕРА
      }
      Arguments {
        Name
        Value {
          ... on EVM_ABI_BigInt_Value_Arg {
            bigInteger
          }
          ... on EVM_ABI_Address_Value_Arg {
            address
          }
        }
      }
    }
  }
}
```

### Query: Фильтр по size (только крупные сделки)
```graphql
# Пример: получить только сделки > $1000
# (нужно декодировать amount из Arguments)
```

### Rate Limits (Bitquery)
- Free tier: 10,000 credits/day
-足 enough для ~1000 запросов

### Документация
- https://docs.bitquery.io/docs/examples/polymarket-api/
- IDE: https://ide.bitquery.io/

---

## 2. Polymarket Subgraph (The Graph)

### Endpoint
```
https://thegraph.com/explorer/subgraphs/6c58N5U4MtQE2Y8njfVrrAfRykzfqajMGeTMEvMmskVz?view=Query&chain=arbitrum-one
```

### Key Queries

#### Get User Positions (Historical PnL)
```graphql
query GetUserPositions {
  userPositions(
    where: {user: "0xWALLET_ADDRESS"}
    first: 1000
    orderBy: timestamp
    orderDirection: desc
  ) {
    id
    user
    realizedPnl
    unrealizedPnl
    tokenId
    market
    timestamp
  }
}
```

#### Get User Trades
```graphql
query GetUserTrades {
  trades(
    where: {user: "0xWALLET_ADDRESS"}
    first: 1000
    orderBy: timestamp
    orderDirection: desc
  ) {
    id
    user
    market
    outcome
    amount
    price
    type
    timestamp
  }
}
```

### Subgraph Types Available
- `polymarket-subgraph` - Main trades, volume
- `pnl-subgraph` - Profit/Loss tracking
- `activity-subgraph` - User activity
- `fpmm-subgraph` - Market data
- `orderbook-subgraph` - Order book

## 2. Polymarket Data API

### Base URL
```
https://data-api.polymarket.com
```

### Get User Positions
```
GET /positions?user=0xWALLET_ADDRESS
```

### Get User Trades
```
GET /trades?user=0xWALLET_ADDRESS&limit=100
```

### Parameters
| Parameter | Type | Default | Max |
|-----------|------|---------|-----|
| limit | int | 100 | 10000 |
| offset | int | 0 | - |
| takerOnly | bool | true | - |
| filterType | string | CASH | CASH/TOKENS |

## 3. Dune Analytics Queries

### Popular Whale Queries
- `dune.com/polymarket_analytics` - Polymarket Analytics dashboard
- `dune.com/genejp999/polymarket-leaderboard` - Leaderboard
- `dune.com/lujanodera/polymarket-analysis` - Analysis

### Sample Query - Top Traders by Volume
```sql
SELECT 
    user,
    COUNT(*) as total_trades,
    SUM(volume) as total_volume,
    AVG(volume) as avg_trade_size,
    MAX(block_time) as last_active
FROM polymarket.trades
WHERE block_time > NOW() - INTERVAL '30 days'
GROUP BY user
ORDER BY total_volume DESC
LIMIT 100
```

## 4. Whale Tracking Services

### Polywhaler (polywhaler.com)
- **Free**: Basic whale alerts, trade history
- **Pro**: $29/month - Deep trade analysis, insider detection, predictions

### Unusual Whales (unusualwhales.com)
- Extended to Polymarket in January 2026
- Tracks large trades and shows trading results
- Flags unusual activity

### PolyTrack (polytrackhq.app)
- Whale alerts
- Twitter account tracking
- Historical analysis

## 5. Twitter/X Whale Trackers

### Key Accounts to Follow
| Account | Focus | Alert Type |
|---------|-------|------------|
| @Polymarket | Official | News, volumes |
| @6to7Figs | Whale alerts | Real-time |
| @polywhaler | Whale tracking | Premium alerts |
| @UnusualWhales | Insider detection | Cross-market |

### How to Use Twitter for Whales
1. Set up lists for Polymarket traders
2. Use TweetDeck filters for "buy" / "sell" / "position"
3. Monitor trending markets for whale activity

## Quality Whale Criteria

### Minimum Requirements (Target >60% win rate)
```
- total_trades >= 100
- win_rate >= 0.60 (60%)
- avg_trade_size >= $50
- last_active_at > NOW() - 30 days
- total_profit_usd > 0
```

### Risk Scoring (1-10)
| Score | Criteria |
|-------|----------|
| 1-3 | Elite (>70% WR, $500k+ volume) |
| 4-6 | Good (60-70% WR, $100k+ volume) |
| 7-8 | Moderate (50-60% WR, $50k+ volume) |
| 9-10 | High risk (<50% WR or <30 days active) |

## Database Schema

### whales table
```sql
wallet_address      VARCHAR(66) PRIMARY KEY
first_seen_at       TIMESTAMP
total_trades        INTEGER
win_rate            DECIMAL(5,4)
total_profit_usd    DECIMAL(20,8)
avg_trade_size_usd  DECIMAL(20,8)
last_active_at      TIMESTAMP
is_active           BOOLEAN
risk_score          INTEGER (1-10)
source              VARCHAR(50)
notes               TEXT
```

### whale_trades table
```sql
whale_id            INTEGER FK
market_id           VARCHAR(255)
side                VARCHAR(10)
size_usd            DECIMAL(20,8)
price               DECIMAL(20,8)
outcome             VARCHAR(50)
is_winner           BOOLEAN
profit_usd          DECIMAL(20,8)
traded_at           TIMESTAMP
```

## Implementation Strategy

### Phase 1: Data Collection
1. Query Polymarket Data API for top traders
2. Get historical positions via Subgraph
3. Calculate win rates and profitability

### Phase 2: Qualification
1. Filter by minimum 100 trades
2. Calculate rolling 30-day win rate
3. Assign risk score

### Phase 3: Integration
1. Store qualified whales in database
2. Set up monitoring for new trades
3. Feed signals to trading bot

## Compliance Notes

- Polymarket ToS: Automated trading is allowed
- No guarantee of profitability from whale copying
- Past performance ≠ future results
- Always verify data independently

## Sources

1. [Polymarket Subgraph Documentation](https://thegraph.com/docs/en/subgraphs/guides/polymarket/) - Jan 2026
2. [Polymarket Data API](https://docs.polymarket.com/developers/subgraph/overview) - Official docs
3. [Polywhaler - Whale Tracker](https://polywhaler.com/) - Dec 2025
4. [PolyTrack Whale Alerts Guide](https://polytrackhq.app/blog/polymarket-whale-alerts) - Dec 2025
5. [Unusual Whales Polymarket](https://www.financemagnates.com/cryptocurrency/unusual-whales-extends-insider-radar-to-prediction-markets-with-unusual-predictions/) - Jan 2026
6. [Dune Analytics Polymarket](https://dune.com/polymarket_analytics) - 2025
7. [PolyTerm - Terminal Tool](https://github.com/NYTEMODEONLY/polyterm) - Feb 2026
8. [Whales Market Tools Guide](https://whales.market/blog/top-10-useful-tools-on-polymarket-part-2/) - Dec 2025

## Appendix

### API Rate Limits
- The Graph: 1000 queries/day (free tier)
- Data API: 15,000 requests/10s
- Dune: 5 queries/10s (free)

### Next Steps for Development
1. Implement Data API client for whale fetching
2. Create background job for updating whale stats
3. Build signal forwarding to trading module
4. Paper trading validation (7 days)
