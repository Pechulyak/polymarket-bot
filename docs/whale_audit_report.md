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
| **Total rows** | 3,932 |
| **Unique addresses** | 3,932 |
| **Duplicates** | 0 ✅ |

---

## 3. Activity Breakdown

### trades_last_3_days

| Метрика | Значение |
|---------|----------|
| Active (>0 trades) | 3,691 (93.9%) |
| Strong (≥3 trades) | 106 (2.7%) |
| Very Strong (≥5 trades) | 44 (1.1%) |
| Extreme (≥10 trades) | 12 (0.3%) |

### Распределение trades_last_3_days

| trades_last_3_days | Count |
|--------------------|-------|
| 58 | 1 |
| 27 | 1 |
| 24 | 1 |
| 21 | 2 |
| 17 | 1 |
| 16 | 1 |
| 14 | 1 |
| 12 | 1 |
| 11 | 2 |
| 10 | 1 |
| 9 | 4 |
| 8 | 1 |
| 7 | 4 |
| 6 | 6 |
| 5 | 17 |
| 4 | 16 |
| 3 | 46 |
| 2 | 203 |
| 1 | 3,382 |
| 0 | 241 |

### trades_last_7_days

| Метрика | Значение |
|---------|----------|
| Active (>0 trades) | 58 (1.5%) |
| Strong (≥5 trades) | 7 (0.2%) |

### days_active

| Метрика | Значение |
|---------|----------|
| Min | 0 |
| Max | 6 |
| Avg | ~1.1 |

### Распределение days_active

| days_active | Count |
|-------------|-------|
| 6 | 5 |
| 5 | 12 |
| 4 | 22 |
| 3 | 60 |
| 2 | 216 |
| 1 | 3,402 |
| 0 | 215 |

**⚠️ ПРОБЛЕМА:** 86.5% китов имеют days_active = 1 — большинство стали "активными" только один день.

---

## 4. Qualification Breakdown

| qualification_path | Count | % |
|--------------------|-------|---|
| ACTIVE | 2,237 | 56.9% |
| NULL | 1,396 | 35.5% |
| CONVICTION | 299 | 7.6% |

### Qualification + Status

| qualification_path | status | Count |
|--------------------|--------|-------|
| ACTIVE | discovered | 2,237 |
| CONVICTION | discovered | ~250 |
| CONVICTION | qualified | ~49 |
| NULL | discovered | 1,396 |

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
| Avg | 6.69 |

**⚠️ ПРОБЛЕМА:** Средний risk_score = 6.69 (высокий). Много "рисковых" китов.

---

## 7. Volume Distribution

| Метрика | Значение |
|---------|----------|
| Min | $1,000 |
| Max | $19,400,000 |
| Avg | $24,660.91 |

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
| 10 | 0x4924...3782 | $211,245 | 3 | 3 |

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

## 12. Whale Trades vs Whales Table Comparison (Last 3 Days)

| Метрика | Значение |
|---------|----------|
| Unique traders in whale_trades (last 3d) | 1,578 |
| Whales with ≥3 trades (whales table) | 106 |

**⚠️ ПРОБЛЕМА:** Gap между 1,578 уникальных трейдеров в whale_trades и 106 китов с ≥3 сделками в whales таблице. Многие трейдеры не синхронизированы.

---

## 13. Paper Trades Analysis (Last 3 Days)

| Метрика | Значение |
|---------|----------|
| Real whale trades | 2,282 |
| Paper trades (virtual) | 26 |
| Conversion ratio | 1.14% |

**⚠️ ПРОБЛЕМА:** Крайне низкая конверсия в paper trading — только 1.14% от реальных сделок.

---

## 14. Strategy Universe Estimate

| Criteria | Count |
|----------|-------|
| Volume ≥ $500 AND trades_last_3_days ≥ 1 | 3,675 |

---

## KEY FINDINGS

### ✅ Сильные стороны

1. Нет дубликатов — все 3,932 адреса уникальны
2. Данные обновляются регулярно (17% за 24h, 34% за 48h)
3. Qualification pipeline работает (ACTIVE: 57%, CONVICTION: 8%)
4. whale_trades таблица содержит 3,493 реальных сделки
5. 106 whales с ≥3 сделками за 3 дня — улучшение с предыдущих 4

### ⚠️ Критические проблемы

1. **86.5% whales = days_active 1** — большинство стали активными только 1 день
2. **Top whales неактивны** — топ-7 по объёму имеют 0 сделок за 3 дня
3. **Высокий risk_score** — средний 6.69 из 8 возможных
4. **Gap синхронизации** — 1,578 трейдеров в whale_trades vs 106 в whales таблице
5. **Низкая конверсия paper trading** — только 1.14% (26 из 2,282)

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
- **Active (≥3 trades/3d):** 106 китов (2.7%)
- **Very Active (≥5 trades/3d):** 44 китов (1.1%)
- **Extreme (≥10 trades/3d):** 12 китов (0.3%)
- **Conviction qualified:** ~49 китов
- **Volume ≥$500 + active:** ~3,691 китов

**Вывод:** Таблица содержит много "discovered" китов с историческим объёмом, но без недавней активности. Для copy trading пригодны ~106 активных китов (≥3 сделок/3 дня).
