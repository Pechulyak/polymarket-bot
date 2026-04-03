# СОСТОЯНИЕ ПРОЕКТА

Обновлено: 2026-03-31
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
  Уведомления - OK  
  updated: 2026-03-29
  task: STRAT-701
  note: unfrozen  
---

## 2. БАЗА ДАННЫХ

- Таблица whales
  status: OK
  updated: 2026-03-23
  task: TRD-419
  note: activity schema

- Таблица whale_trades
  status: OK
  updated: 2026-03-27
  task: ARC-503
  note: legacy fields removed (is_winner, profit_usd)

- Таблица paper_trades
  status: OK
  updated: 2026-03-29
  task: STRAT-701
  note: unfrozen, filtered by copy_status='paper'

- Таблица trades
  status: OK
  updated: 2026-03-29
  task: STRAT-701
  note: unfrozen

- Таблица whale_trade_roundtrips
  status: OK
  updated: 2026-03-26
  task: ARC-502-C
  note: settlement via CLOB API working
  issue: tested on 4 closed markets, 23 roundtrips settled

- Таблица bankroll
  status: OK
  updated: 2026-03-29
  task: STRAT-701
  note: reset to $100, unfrozen

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
  status: ACTIVE
  updated: 2026-03-30
  task: BUG-504
  note: paper(2)+tracked polling, duplicate detection fixed

- bot (main)
  status: PARTIAL
  updated: 2026-03-23
  task: SYS-326
  note: no execution

- roundtrip_builder
  status: OK
  updated: 2026-03-26
  task: TRD-427
  note: Теперь запускает --settle каждые 2 часа

- paper_settlement
  status: DISABLED
  updated: 2026-03-26
  task: SYS-601-FIX
  note: broken - file does not exist

---

## 4. ОСНОВНЫЕ PYTHON-ФАЙЛЫ

- whale_detector.py
  status: ACTIVE
  updated: 2026-04-02
  task: PHASE1-002
  note: записи через WhaleTradesRepo

- whale_tracker.py
  status: OK
  updated: 2026-04-02
  task: PHASE1-003
  note: save_whale_trade через WhaleTradesRepo

- whale_trade_writer.py
  status: DEPRECATED
  updated: 2026-04-02
  task: PHASE1-003
  note: заменён WhaleTradesRepo, используется только virtual_bankroll

- virtual_bankroll.py
  status: FROZEN
  updated: 2026-03-23
  task: SYS-326
  note: disabled

- main.py
  status: PARTIAL
  updated: 2026-03-26
  task: SYS-601-FIX
  note: roundtrip jobs disabled (duplicates container)

- copy_trading_engine.py
  status: FROZEN
  updated: 2026-03-23
  task: SYS-326
  note: disabled

- whale_trade_writer.py
  status: DEPRECATED
  updated: 2026-04-02
  task: PHASE1-001
  note: replaced by whale_trades_repo.py

- whale_trades_repo.py
  status: OK
  updated: 2026-04-02
  task: PHASE1-001
  note: единая точка записи whale_trades

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

- Tier system
  status: UPDATED
  updated: 2026-03-26
  task: TRD-426
  note: thresholds fixed (HOT: 1d, WARM: 7d)
  hot_count: 593
  warm_count: 860
  cold_count: 5

- whale_trades → paper_trades
  status: OK
  updated: 2026-03-30
  task: BUG-502
  note: real-time verified, 2 paper whales

- paper_trades → trades
  status: OK
  updated: 2026-03-29
  task: STRAT-701
  note: unfrozen

- settlement pipeline
  status: OK
  updated: 2026-03-31
  task: BUG-601-FIX
  note: CLOB API, 459 trades closed

- whales P&L pipeline
  status: OK
  updated: 2026-03-26
  task: ARC-502-D

- notifications pipeline
  status: OK
  updated: 2026-03-29
  task: STRAT-701
  note: unfrozen

- pipeline_monitor
  status: ACTIVE
  updated: 2026-04-02
  task: PHASE1-004
  note: cron */30, Telegram alerts every 30min

---

## WHALE COPY SELECTION

- P&L Gate
  status: ACTIVE
  updated: 2026-03-29
  task: STRAT-701
  note: min 5 roundtrips, WR ≥60%, PnL >$0, tier HOT/WARM

- Kelly Sizing
  status: ACTIVE
  updated: 2026-03-29
  task: STRAT-701
  note: fraction 0.25, max_position 5%

- Selected Whales
  status: PAPER
  updated: 2026-03-30
  task: BUG-502
  note: 0x32ed (WR 81.8%, +$6599), 0x2652dd (WR 100%, +$2917), 0xd48a (WR 87.5%, +$1726)

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

- PROJECT_CHANGELOG.md
  status: OK
  updated: 2026-03-25
  task: ARC-502-B
  note: main changelog


  ## 9. DAILY DATA SNAPSHOT

<!-- AUTO-GENERATED: This section is updated by scripts/run_data_check.py -->
### 2026-03-31

snapshot_date: 2026-03-31
database: polymarket
schema: public

whales_rows: 0
whale_trades_rows: 22219
paper_trades_rows: 1442
paper_trade_notifications_rows: 0
trades_rows: 82
bankroll_rows: 2

whale_trades_last_24h: 6715
paper_trades_last_24h: 1302
notifications_last_24h: 0

conversion_whale_to_paper_48h: 17.42%
conversion_paper_to_notifications_48h: 0.0%

stale_tables_24h:
- paper_trade_notifications

notes:
- bankroll contains only test data
- trades table contains only virtual test trades

<!-- END AUTO-GENERATED -->

### 2026-04-03

snapshot_date: 2026-04-03
database: polymarket
schema: public

whales_rows: 0
whale_trades_rows: 21378
paper_trades_rows: 1732
paper_trade_notifications_rows: 0
trades_rows: 1971
bankroll_rows: 151

whale_trades_last_24h: 1313
paper_trades_last_24h: 353
notifications_last_24h: 0

conversion_whale_to_paper_48h: 24.93%
conversion_paper_to_notifications_48h: 0.0%

stale_tables_24h:
- paper_trade_notifications

notes:
- bankroll contains only test data
- trades table contains only virtual test trades

<!-- END AUTO-GENERATED -->

### 2026-04-02

snapshot_date: 2026-04-02
database: polymarket
schema: public

whales_rows: 0
whale_trades_rows: 19856
paper_trades_rows: 1379
paper_trade_notifications_rows: 0
trades_rows: 1618
bankroll_rows: 101

whale_trades_last_24h: 1649
paper_trades_last_24h: 395
notifications_last_24h: 0

conversion_whale_to_paper_48h: 26.62%
conversion_paper_to_notifications_48h: 0.0%

stale_tables_24h:
- paper_trade_notifications

notes:
- bankroll contains only test data
- trades table contains only virtual test trades

<!-- END AUTO-GENERATED -->

### 2026-04-01

snapshot_date: 2026-04-01
database: polymarket
schema: public

whales_rows: 0
whale_trades_rows: 30349
paper_trades_rows: 5219
paper_trade_notifications_rows: 0
trades_rows: 1160
bankroll_rows: 13

whale_trades_last_24h: 8130
paper_trades_last_24h: 3777
notifications_last_24h: 0

conversion_whale_to_paper_48h: 34.21%
conversion_paper_to_notifications_48h: 0.0%

stale_tables_24h:
- paper_trade_notifications

notes:
- bankroll contains only test data
- trades table contains only virtual test trades

<!-- END AUTO-GENERATED -->

---

### Current State (2026-03-31)

trades: 944
closed: 459
open: 485
balance: $909.19
pnl: -$90.80

---

### 2026-03-30

snapshot_date: 2026-03-30
database: polymarket
schema: public

whales_rows: 0
whale_trades_rows: 13894
paper_trades_rows: 140
paper_trade_notifications_rows: 0
trades_rows: 0
bankroll_rows: 1

whale_trades_last_24h: 1369
paper_trades_last_24h: 140
notifications_last_24h: 0

conversion_whale_to_paper_48h: 5.29%
conversion_paper_to_notifications_48h: 0.0%

stale_tables_24h:
- paper_trade_notifications
- trades

notes:
- bankroll contains only test data
- trades table contains only virtual test trades

<!-- END AUTO-GENERATED -->







