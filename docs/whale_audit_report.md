# Whale Table Quality Audit Report

**Дата:** 2026-03-09  
**Таблица:** public.whales  
**БД:** polymarket

---

## 1. Структура таблицы

| Поле | Тип данных | Default |
|------|------------|---------|
| id | integer | nextval |
| wallet_address | varchar | NOT NULL |
| first_seen_at | timestamp | now() |
| total_trades | integer | 0 |
| win_rate | numeric | 0 |
| total_profit_usd | numeric | 0 |
| avg_trade_size_usd | numeric | 0 |
| last_active_at | timestamp | now() |
| is_active | boolean | true |
| risk_score | integer | 5 |
| source | varchar | NULL |
| notes | text | NULL |
| created_at | timestamp | now() |
| updated_at | timestamp | now() |
| total_volume_usd | numeric | 0 |
| status | varchar | 'discovered' |
| trades_last_3_days | integer | 0 |
| days_active | integer | 0 |
| qualification_path | varchar | NULL |
| trades_last_7_days | integer | 0 |

**Всего полей:** 20

---

## 2. Общая статистика

| Метрика | Значение |
|---------|----------|
| **Total rows** | 3,915 |
| **Unique addresses** | 3,915 |
| **Duplicates** | 0 ✅ |

---

## 3. Activity Breakdown

### trades_last_3_days

| Метрика | Значение |
|---------|----------|
| Active (>0 trades) | 3,673 (93.8%) |
| Strong (≥3 trades) | 4 (0.1%) |

### Распределение trades_last_3_days

| trades_last_3_days | Count |
|--------------------|-------|
| 5 | 1 |
| 4 | 1 |
| 3 | 2 |
| 2 | 47 |
| 1 | 3,622 |
| 0 | 242 |

### trades_last_7_days

| Метрика | Значение |
|---------|----------|
| Active (>0 trades) | 58 (1.5%) |
| Strong (≥5 trades) | 7 (0.2%) |

### days_active

| Метрика | Значение |
|---------|----------|
| Min | 0 |
| Max | 1 |
| Avg | 0.95 |

**⚠️ ПРОБЛЕМА:** Max days_active = 1 указывает на то, что поле days_active не обновляется корректно.

---

## 4. Qualification Breakdown

| qualification_path | Count | % |
|--------------------|-------|---|
| ACTIVE | 2,243 | 57.3% |
| NULL | 1,372 | 35.0% |
| CONVICTION | 300 | 7.7% |

### Qualification + Status

| qualification_path | status | Count |
|--------------------|--------|-------|
| ACTIVE | discovered | 2,243 |
| CONVICTION | discovered | 251 |
| CONVICTION | qualified | 49 |
| NULL | discovered | 1,374 |

---

## 5. Status Distribution

| Status | Count |
|--------|-------|
| discovered | 3,868 (98.8%) |
| qualified | 49 (1.2%) |

---

## 6. Risk Score Distribution

| Метрика | Значение |
|---------|----------|
| Min | 1 |
| Max | 8 |
| Avg | 6.68 |

**⚠️ ПРОБЛЕМА:** Средний risk_score = 6.68 (высокий). Много "рисковых" китов.

---

## 7. Volume Distribution

| Метрика | Значение |
|---------|----------|
| Min | $1,000 |
| Max | $19,400,000 |
| Avg | $24,777.50 |

---

## 8. Top Whales (by volume)

| # | Wallet | Volume (USD) | Trades 3d | Days Active |
|---|--------|--------------|-----------|-------------|
| 1 | 0x94f1...4c7a | $19,400,000 | 0 | 1 |
| 2 | 0xac44...fbd7 | $14,900,000 | 0 | 1 |
| 3 | 0x03e8...1697 | $13,900,000 | 0 | 1 |
| 4 | 0x8764...2604 | $12,200,000 | 0 | 1 |
| 5 | 0x0720...1cdb | $9,600,000 | 0 | 1 |
| 6 | 0x1496...429 | $8,900,000 | 0 | 1 |
| 7 | 0xd25c...4d20 | $3,500,000 | 0 | 1 |
| 8 | 0xadc2...1c9 | $399,600 | 1 | 1 |
| 9 | 0x7e97...d54 | $249,750 | 1 | 1 |
| 10 | 0x4924...3782 | $211,245 | 1 | 1 |

**⚠️ ПРОБЛЕМА:** Top 7 китов по объёму имеют 0 trades в последние 3 дня — исторические данные, не активны.

---

## 9. Freshness

| Метрика | Значение |
|---------|----------|
| Oldest record | 2026-02-23 18:18:13 |
| Newest record | 2026-03-09 11:25:52 |
| Updated last 24h | 666 (17.0%) |
| Updated last 48h | 1,317 (33.6%) |

---

## 10. Real Trading Activity

| Criteria | Count |
|----------|-------|
| trades_last_3_days ≥ 3 AND days_active ≥ 1 | 4 |

**⚠️ ПРОБЛЕМА:** Только 4 кита с "реальной" торговой активностью (≥3 сделки за 3 дня).

---

## 11. Whale Trades History

| Метрика | Значение |
|---------|----------|
| Total trades in whale_trades | 3,493 |
| Unique whales with trades | 2,235 |

---

## 12. Strategy Universe Estimate

| Criteria | Count |
|----------|-------|
| Volume ≥ $500 AND trades_last_3_days ≥ 1 | 3,675 |

---

## KEY FINDINGS

### ✅ Сильные стороны

1. Нет дубликатов — все 3,915 адресов уникальны
2. Данные обновляются регулярно (17% за 24h, 34% за 48h)
3. Qualification pipeline работает (ACTIVE: 57%, CONVICTION: 8%)
4. whale_trades таблица содержит 3,493 реальных сделки

### ⚠️ Критические проблемы

1. **days_active = 1 max** — поле не обновляется, бесполезно для анализа
2. **Только 4 active whales** — 0.1% от общего числа имеют ≥3 сделки за 3 дня
3. **Top whales неактивны** — топ-7 по объёму имеют 0 сделок за 3 дня
4. **Высокий risk_score** — средний 6.68 из 8 возможных
5. **93.8% имеют только 1 сделку** — непрерывная активность отсутствует

### 📊 Quality Score

| Аспект | Оценка |
|--------|--------|
| Data Integrity | ✅ 100% |
| Freshness | ⚠️ 34% (48h) |
| Activity Tracking | ❌ 0.1% active |
| Qualification | ⚠️ 57% qualified |
| Risk Scoring | ❌ High risk avg |

---

## RECOMMENDATIONS FOR STRATEGY

### Daily Snapshot

**Включать в snapshot:**
- ✅ qualification_path
- ✅ trades_last_3_days
- ✅ total_volume_usd
- ✅ status (discovered/qualified)
- ✅ risk_score

**Не включать (бесполезно):**
- ❌ days_active (всегда = 1)
- ❌ trades_last_7_days (только 58 активных)

### Очистка таблицы (рекомендуется)

1. **Удалить китов с 0 trades за 30 дней** — переместить в архив
2. **Удалить дубликаты по wallet_address** — если появятся
3. **Пересмотреть risk_score алгоритм** — текущий слишком консервативен (6.68 avg)

### Reality Check

Текущий "real whale" universe:
- **Active (≥3 trades/3d):** 4 кита
- **Conviction qualified:** 49 китов
- **Volume ≥$500 + active:** 3,675 китов

**Вывод:** Таблица содержит много " discoverd" китов с историческим объёмом, но без недавней активности. Для copy trading пригодны только ~50 qualified китов.
