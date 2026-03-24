# СОСТОЯНИЕ ПРОЕКТА

Обновлено: 2026-03-23  
Версия: v2_clean  
Фаза: Реструктуризация (после cleanup)

---

## 1. РЕЖИМ ПРОЕКТА
-Активные стратегии:
- Whale Copy: IN_WORK
- Arbitrage: FROZEN
- Anomaly Detection: FROZEN

- Режим торговли
  status: OK
  updated: 2026-03-23
  task: SYS-326
  note: paper active

- Режим наблюдения
  status: OK
  updated: 2026-03-23
  task: SYS-326
  note: downstream off

- Trading Metrics (цели выхода в live)
  status: IN_WORK
  updated: 2026-03-23
  task: STRAT-001
  note: targets defined

  target_roi: 25%
  target_winrate: >60%
  target_drawdown: controlled

- Риск-контур (Kelly)
  status: OK
  updated: 2026-03-04
  task: TRD-201
  note: quarter kelly

  kelly_fraction: 0.25
  max_position: 2%

- Edge статус
  status: IN_WORK
  updated: 2026-03-23
  task: STRAT-002
  note: not confirmed

- API статус
  status: ok
  updated: 2026-03-23
  task: 
  note: 
  issue: 

- Telegram
  API - ok
  Уведомления -FROZEN  
---

## 2. БАЗА ДАННЫХ

- Таблица whales
  status: OK
  updated: 2026-03-23
  task: TRD-419
  note: activity schema

- Таблица whale_trades
  status: IN_WORK
  updated: 2026-03-23
  task: TRD-420
  note: staging redesign
  issue: ingestion incomplete

- Таблица paper_trades
  status: OK
  updated: 2026-03-23
  task: TRD-406
  note: trigger stable

- Таблица trades
  status: FROZEN
  updated: 2026-03-23
  task: SYS-326
  note: execution off

- Таблица bankroll
  status: FROZEN
  updated: 2026-03-23
  task: SYS-326
  note: disabled

---

## 3. КОНТЕЙНЕРЫ

- postgres
  status: OK
  updated: 2026-03-23
  task: SYS-301
  note: running

- redis
  status: OK
  updated: 2026-03-23
  task: SYS-301
  note: running

- whale_detector
  status: FROZEN
  updated: 2026-03-23
  task: TRD-415
  note: stopped

- bot (main)
  status: PARTIAL
  updated: 2026-03-23
  task: SYS-326
  note: no execution

---

## 4. ОСНОВНЫЕ PYTHON-ФАЙЛЫ

- whale_detector.py
  status: IN_WORK
  updated: 2026-03-23
  task: TRD-419
  note: new fields

- whale_tracker.py
  status: IN_WORK
  updated: 2026-03-23
  task: TRD-413
  note: ingestion redesign
  issue: api limit 500

- virtual_bankroll.py
  status: FROZEN
  updated: 2026-03-23
  task: SYS-326
  note: disabled

- main.py
  status: PARTIAL
  updated: 2026-03-23
  task: SYS-326
  note: execution off

- copy_trading_engine.py
  status: FROZEN
  updated: 2026-03-23
  task: SYS-326
  note: disabled

---

## 5. PIPELINE

- Discovery pipeline
  status: IN_WORK
  updated: 2026-03-23
  task: TRD-420
  note: redesign staged

- Qualification pipeline
  status: PARTIAL
  updated: 2026-03-23
  task: TRD-419
  note: activity-based

- whale_trades → paper_trades
  status: OK
  updated: 2026-03-23
  task: TRD-406
  note: trigger active

- paper_trades → trades
  status: FROZEN
  updated: 2026-03-23
  task: SYS-326
  note: disabled

- settlement pipeline
  status: FROZEN
  updated: 2026-03-23
  task: SYS-326
  note: disabled

- notifications pipeline
  status: FROZEN
  updated: 2026-03-23
  task: SYS-326
  note: disabled

---

## 6. БЕЗОПАСНОСТЬ

- Публичные порты
  status: OK
  updated: 2026-03-23
  task: SYS-401
  note: internal only

- Доступ к БД
  status: OK
  updated: 2026-03-23
  task: SYS-401
  note: docker network

- .env доступ
  status: OK
  updated: 2026-03-23
  task: SYS-401
  note: restricted

---


## 7. АКТИВНЫЕ БЛОКЕРЫ

- Whale ingestion
  status: BLOCKED
  updated: 2026-03-23
  task: TRD-413
  note: api limit
  issue: no per-wallet fetch

---

## 8. ДОКУМЕНТАЦИЯ

- init_db.sql
  status: OK
  updated: 2026-03-23
  task: TRD-418
  note: schema updated

- TASK_BOARD.md
  status: OK
  updated: 2026-03-23
  task: SYS-500
  note: cleaned

- PROJECT_STATE.md
  status: OK
  updated: 2026-03-23
  task: SYS-500
  note: restructured

- CHAT GOVERNANCE.md
  status: OK
  updated: 2026-03-23
  task: SYS-302
  note: active

- PROJECT_STATE_GOVERNANCE.md
  status: OK
  updated: 2026-03-24
  task: 
  note: governance rules


  ## 9. DAILY DATA SNAPSHOT

<!-- AUTO-GENERATED: This section is updated by scripts/run_data_check.py -->
### 2026-03-23

snapshot_date: 2026-03-23
database: polymarket
schema: public

whales_rows: 0
whale_trades_rows: 7648
paper_trades_rows: 730
paper_trade_notifications_rows: 528
trades_rows: 42
bankroll_rows: 14

whale_trades_last_24h: 35
paper_trades_last_24h: 4
notifications_last_24h: 0

conversion_whale_to_paper_48h: 1.28%
conversion_paper_to_notifications_48h: 0.0%

stale_tables_24h:
- paper_trade_notifications
- trades
- bankroll

notes:
- bankroll contains only test data
- trades table contains only virtual test trades

<!-- END AUTO-GENERATED -->

### 2026-03-24

snapshot_date: 2026-03-24
database: polymarket
schema: public

whales_rows: 0
whale_trades_rows: 7648
paper_trades_rows: 730
paper_trade_notifications_rows: 528
trades_rows: 42
bankroll_rows: 14

whale_trades_last_24h: 11
paper_trades_last_24h: 0
notifications_last_24h: 0

conversion_whale_to_paper_48h: 1.28%
conversion_paper_to_notifications_48h: 0.0%

stale_tables_24h:
- paper_trades
- paper_trade_notifications
- trades
- bankroll

notes:
- bankroll contains only test data
- trades table contains only virtual test trades

<!-- END AUTO-GENERATED -->
