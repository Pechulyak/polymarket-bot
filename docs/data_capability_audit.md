# Polymarket Data API — Capability Audit

**Дата:** 2026-02-28  
**Источник:** Анализ исходного кода [`whale_tracker.py`](src/research/whale_tracker.py) и [`polymarket_data_client.py`](src/research/polymarket_data_client.py)

---

## 1. Endpoints Analysis

### 1.1 GET /trades

**Используемые поля в коде:**

| Field | Code Usage | Available |
|-------|------------|-----------|
| `id` | `item.get("id", "")` | ✅ YES |
| `conditionId` / `tokenId` | `item.get("conditionId", item.get("tokenId", ""))` | ✅ YES |
| `side` | `item.get("side", "buy").lower()` | ✅ YES |
| `amount` | `item.get("amount", 0)` → `size_usd` | ✅ YES |
| `price` | `item.get("price", 0)` | ✅ YES |
| `timestamp` | `item.get("timestamp", ...)` | ✅ YES |
| `fee` | `item.get("fee", 0)` | ✅ YES |
| `proxyWallet` / `user` | Фильтр по адресу | ✅ YES |

**НЕдоступные поля:**

| Field | Reason |
|-------|--------|
| `is_winner` | **NOT provided by API** — нет данных о результате сделки |
| `profit` | **NOT provided by API** — нет данных о PnL |
| `outcome` | Возвращается в `/trades` без user filter, но НЕ в `/trades?user=...` |
| `settled_at` | **NOT provided by API** — нет данных о расчёте |

**Лимиты и пагинация:**
- `limit` parameter: max 1000 (константа `MAX_TRADES_PER_QUERY = 1000`)
- Rate limit: ~15000/10s (general), требует API key для повышенных лимитов

---

### 1.2 GET /positions

**Используемые поля в коде:**

| Field | Code Usage | Available |
|-------|------------|-----------|
| `conditionId` / `tokenId` | `item.get("conditionId", item.get("tokenId", ""))` | ✅ YES |
| `outcome` | `item.get("outcome", "Yes")` | ✅ YES |
| `size` | `item.get("size", 0)` | ✅ YES |
| `avgPrice` | `item.get("avgPrice", 0)` → `entry_price` | ✅ YES |
| `currentPrice` | `item.get("currentPrice", 0)` | ✅ YES |
| `unrealizedPnl` | `item.get("unrealizedPnl", 0)` | ✅ YES |
| `timestamp` | `item.get("timestamp", ...)` | ✅ YES |

**НЕдоступные поля:**

| Field | Reason |
|-------|--------|
| `realizedPnl` | **NOT provided by API** — только unrealized PnL |
| `closed_at` | **NOT provided by API** — нет данных о закрытии позиции |
| `is_settled` | **NOT provided by API** |

---

## 2. Metrics Availability

| Metric | API Field | Available | Notes |
|--------|-----------|-----------|-------|
| **ROI** | — | **NO** | Невозможно рассчитать без knowing initial bankroll и realized PnL |
| **Sharpe Ratio** | — | **NO** | Требует historical returns series, недоступно |
| **Drawdown** | — | **NO** | Требует historical balance, недоступно |
| **Win Rate** | `side` only | **PARTIAL** | Текущая логика: buy = win, sell = loss — **НЕВЕРНО** |
| **Profit** | `unrealizedPnl` | **PARTIAL** | Только unrealized PnL, без realized |
| **Total Volume** | `amount` | ✅ YES | Сумма всех сделок |
| **Avg Trade Size** | `amount` | ✅ YES | Средний размер сделки |
| **Last Active** | `timestamp` | ✅ YES | Время последней сделки |
| **Risk Score** | Calculated | ✅ YES | Вычисляется локально |

---

## 3. Key Findings

### 3.1 Critical Issue: Win Rate Calculation is Wrong

**Текущая логика в [`whale_tracker.py:329-335`](src/research/whale_tracker.py:329):**
```python
if trade.side.lower() == "buy":
    if trade.size_usd > 0:
        wins += 1
        total_profit += trade.size_usd * (Decimal("1") - trade.price)
else:
    if trade.size_usd > 0:
        total_profit += trade.size_usd * trade.price
```

**Проблема:** Эта логика предполагает, что:
- Все BUY — выигрышные
- Все SELL — проигрышные

**Это неверно**, потому что:
1. API не предоставляет `is_winner` — результат сделки неизвестен
2. Win rate зависит от outcome (Yes/No), а не от side (buy/sell)
3. Правильный расчёт требует данных о resolved markets

### 3.2 Profit Calculation is Incorrect

**Текущая логика:**
```python
total_profit += trade.size_usd * (Decimal("1") - trade.price)  # для BUY
total_profit += trade.size_usd * trade.price  # для SELL
```

**Проблемы:**
1. Не учитывает fees
2. Не учитывает реальный outcome (рынок может быть No, а не Yes)
3. Не различает realized и unrealized PnL

### 3.3 Missing Data for Proper Metrics

Для полноценных метрик не хватает:
- `is_winner` — результат сделки
- `realizedPnl` — реальная прибыль
- `settled_at` — время расчёта
- `outcome` в filtered queries

---

## 4. Recommendations

### 4.1 Что можно рассчитать из API

| Metric | Status | Implementation |
|--------|--------|-----------------|
| Total Volume | ✅ Ready | `sum(trade.size_usd)` |
| Avg Trade Size | ✅ Ready | `total_volume / count` |
| Last Active | ✅ Ready | `max(trade.timestamp)` |
| Risk Score | ✅ Ready | Локальное вычисление |
| Unrealized PnL | ✅ Ready | Из `/positions` endpoint |

### 4.2 Что НЕЛЬЗЯ рассчитать из API

| Metric | Workaround |
|--------|------------|
| ROI | Требует external bankroll tracking |
| Sharpe | Требует historical data, недоступно |
| Drawdown | Требует historical balance |
| True Win Rate | Требует `is_winner` от API |
| Realized PnL | Требует `realizedPnl` от API |

### 4.3 Что нужно исправить

1. **Убрать некорректный Win Rate** — текущая формула даёт неверные результаты
2. **Добавить disclaimer** — API не предоставляет данные о результатах сделок
3. **Использовать только доступные метрики** — volume, avg_size, last_active, risk_score

---

## 5. API Stability Notes

**Из исходного кода:**

- Timeout: 30 seconds (`aiohttp.ClientTimeout(total=30)`)
- Error handling: Логирует 429, 500, network errors
- Rate limits: Не обрабатываются явно (возможны 429 errors)

**Рекомендации:**
- Добавить retry с exponential backoff
- Мониторить 429 responses
- Кэшировать данные для уменьшения запросов
