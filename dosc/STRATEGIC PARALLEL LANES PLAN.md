STRATEGIC PARALLEL LANES PLAN

Version: 1.0
Date: 2026-03-01
Status: APPROVED BY STRATEGY

1. EXECUTION LANE (PRIMARY)
Whale Model Refactor — Dual Path
Цель

Обеспечить ≥ 15 qualified whales и запуск портфельного paper.

1.1 Изменения в БД
Таблица: whales
ALTER TABLE whales
ADD COLUMN qualification_path VARCHAR(20);

Допустимые значения:

NULL

'ACTIVE'

'CONVICTION'
1.2 Метрики
Добавить расчёт:
trades_last_7_days
avg_trade_size_usd
Если avg_trade_size_usd отсутствует:

avg_trade_size_usd = total_volume_usd / NULLIF(total_trades, 0)
1.3 Qualification Logic (v2_dual_path)

Файл:
src/research/whale_detector.py
PATH A — ACTIVE
active_path = (
    whale.total_trades >= 10 and
    whale.total_volume_usd >= Decimal("500") and
    whale.trades_last_7_days >= 3 and
    whale.days_active >= 1 and
    whale.risk_score <= 6
)
PATH B — CONVICTION
conviction_path = (
    whale.total_volume_usd >= Decimal("10000") and
    whale.avg_trade_size_usd >= Decimal("2000") and
    whale.trades_last_7_days >= 1 and
    whale.days_active >= 1 and
    whale.risk_score <= 6
)
Присвоение:
if active_path:
    whale.qualification_path = "ACTIVE"
elif conviction_path:
    whale.qualification_path = "CONVICTION"
else:
    whale.qualification_path = None
1.4 Snapshot Audit (обязательно)
SELECT qualification_path, COUNT(*)
FROM whales
GROUP BY qualification_path;
SELECT COUNT(*) FROM whales
WHERE qualification_path IS NOT NULL;
1.5 KPI

≥ 15 qualified whales

Ranking работает

Нет регрессий

PROJECT_STATE обновлён

2. RESEARCH LANE — ARBITRAGE (PHASE A ONLY)
Цель
Определить наличие repeatable mispricing без реализации execution.

2.1 Ограничение
На данном этапе:
НЕ использовать Roo
НЕ писать orderbook monitor
НЕ писать execution

Только dry feasibility.

2.2 Данные

Использовать:
CLOB API (snapshot)
Только best ask / best bid
2.3 Исследование
Выборка:
≥ 50 рынков:
25 обычных
25 быстрых

Расчёт (mid-screening):
mid_deviation = abs((mid_yes + mid_no) - 1)
Считать долю рынков, где:
mid_deviation > 0.02
mid_deviation > 0.03
mid_deviation > 0.05
2.4 Фильтр для перехода к Phase B

Если:
10% рынков имеют mid_deviation > 0.02
→ разрешено переходить к Orderbook Monitor Phase
Иначе:
→ направление закрывается
3. RESEARCH LANE — SMART MONEY (PHASE A)
Цель
Определить repeatable event-based edge.
3.1 Триггеры
T1:
address_age < 7 дней
trade_size > $10000

T2:
volume spike > 20% за 10 минут

T3:

probability shift > 10% за 15 минут

3.2 Минимальная выборка

≥ 30 событий на каждый триггер.

3.3 Для каждого события считать:
1h return
6h return
24h return
winrate
std deviation
false positive rate

3.4 Решение

Если:
median 6h return > 1%
winrate > 55%
sample size ≥ 30
→ переход к Phase B (архитектура детекции)
Иначе:
→ закрыть направление

4. ПАРАЛЛЕЛЬНОСТЬ
Линия	Исполнитель	Roo
Whale Dual Path	Roo	Да
Arbitrage Phase A	Research	Нет
Smart Money Phase A	Research	Нет
5. ЗАПРЕТЫ

Roo не реализует Arbitrage или Smart Money до approval Strategy.
Никаких execution модулей без Decision Memo.
Никакого live.

6. NEXT CHECKPOINT
Через 7 дней Strategy получает:
Dual Path Snapshot
Arbitrage Decision Memo
Smart Money Decision Memo
И принимает решение о Phase B для каждой линии.



# SMART MONEY — EVENT STUDY SPECIFICATION
Версия: 1.0  
Дата: 2026-03-01  
Статус: RESEARCH PHASE (без реализации Roo)

---

# 1. ЦЕЛЬ

Определить, существует ли статистически значимый и повторяемый edge
после аномальных событий (event-based signals).

Важно:
Edge измеряется по изменению цены/вероятности после события,
а НЕ по settlement outcome адреса.

---

# 2. ОБЩИЕ ДОПУЩЕНИЯ

- Используется единый источник цены:
  - приоритет: mid/mark price
  - иначе: last trade price
- Один и тот же источник цены используется для:
  - расчёта триггера
  - расчёта return
- Никаких смешанных источников данных.

---

# 3. ТРИГГЕРЫ (СТРОГО ФОРМАЛИЗОВАНЫ)

## T1 — Новый адрес + объём > $10,000

Событие фиксируется, если:

1. Адрес не встречался в течение 30 дней (lookback window)
2. В течение 30 минут с момента первой активности
   суммарный объём сделок > $10,000 (notional)

Определение "новый":
- новый для всей платформы Polymarket,
  а не просто новый для конкретного рынка

---

## T2 — Volume Spike >20% за 10 минут

Событие фиксируется, если:

volume(10m) > 1.2 × baseline_volume(10m)

Baseline:
- медиана объёма 10-минутных окон
- за предыдущие 6 часов (36 окон)

---

## T3 — Price Move >10% за 15 минут

Событие фиксируется, если:

|P(t0+15m) − P(t0)| / P(t0) ≥ 0.10

Где:
P = выбранная консистентная цена (mid/last)

---

# 4. ПРАВИЛА ОТБОРА СОБЫТИЙ

## 4.1 Минимальная выборка
- ≥ 30 событий на каждый триггер

## 4.2 Отсечение пересечений

- События одного триггера на одном рынке
  должны быть разнесены минимум на 24 часа

- Формируются два набора:
  - RAW (с пересечениями)
  - CLEAN (без пересечений между триггерами)

## 4.3 Фильтр ликвидности (желательно)

Исключить рынки:
- с экстремальным спредом
- с микро-объёмом

---

# 5. ДАННЫЕ ПО КАЖДОМУ СОБЫТИЮ

Для каждого события фиксируется:

- market_id
- market_name
- trigger_type (T1/T2/T3)
- timestamp_T0
- P0
- P_1h
- P_6h
- P_24h

---

# 6. МЕТРИКИ

## 6.1 Returns

r_1h = (P_1h − P0) / P0  
r_6h = (P_6h − P0) / P0  
r_24h = (P_24h − P0) / P0  

---

## 6.2 Winrate

win_1h = r_1h > 0  
win_6h = r_6h > 0  
win_24h = r_24h > 0  

---

## 6.3 False Positive Rate

FP_1h = share(r_1h ≤ 0)  
FP_6h = share(r_6h ≤ 0)  
FP_24h = share(r_24h ≤ 0)  

---

## 6.4 Дисперсия

std(r_1h)  
std(r_6h)  
std(r_24h)  

---

# 7. СТАТИСТИЧЕСКАЯ ПРОВЕРКА

Для каждого триггера × горизонта:

## 7.1 Параметрический тест
- t-test: mean(return) > 0 (информативный)

## 7.2 Непараметрический анализ
- bootstrap CI для mean
- bootstrap CI для median
- sign test (winrate > 50%)

## 7.3 Контроль множественных проверок
- Benjamini–Hochberg FDR
- 9 тестов (3 триггера × 3 горизонта)

---

# 8. КРИТЕРИИ ПРИЗНАНИЯ EDGE (PHASE A)

Триггер считается перспективным, если одновременно:

- median return > 0
- winrate > 50%
- FP rate < 45%
- bootstrap CI mean не включает 0
- частота событий достаточная (не < 1 в неделю)

---

# 9. ЧАСТОТА СОБЫТИЙ

Для каждого триггера определить:

- events_per_day
- распределение по рынкам
- сезонность (если заметна)

---

# 10. ОЦЕНКА КАПИТАЛА

Исходя из ограничений:

position_cap = 2% bankroll

Минимальный банкролл:

min_bankroll ≈ trade_size / 0.02  
= trade_size × 50

Определить trade_size в 3 сценариях:

- conservative
- moderate
- aggressive

---

# 11. DELIVERABLE ДЛЯ STRATEGY

Итоговый отчёт должен содержать:

Для каждого триггера и горизонта:

- N событий (RAW и CLEAN)
- mean
- median
- std
- winrate
- FP rate
- bootstrap CI
- FDR-corrected p-values
- events/day
- verdict: YES / WEAK / NO
- tradeability notes

---

# 12. ЗАПРЕТЫ

- Никакой реализации детектора
- Никакого кода для Roo
- Никакого execution
- Только аналитика

Переход к Phase B возможен
только после утверждения Strategy.