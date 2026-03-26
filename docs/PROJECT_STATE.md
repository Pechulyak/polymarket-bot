# СОСТОЯНИЕ ПРОЕКТА

Обновлено: 2026-03-26
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

- Таблица whale_trade_roundtrips
  status: OK
  updated: 2026-03-26
  task: ARC-502-C
  note: settlement via CLOB API working
  issue: tested on 4 closed markets, 23 roundtrips settled

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
  status: ACTIVE
  updated: 2026-03-26
  task: TRD-426
  note: tier thresholds fixed, running
  updated: 2026-03-23
  task: TRD-415
  note: stopped

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
  fix: 757 OPEN roundtrips теперь будут обновляться при закрытии рынков

- paper_settlement
  status: DISABLED
  updated: 2026-03-26
  task: SYS-601-FIX
  note: broken - file does not exist

---

## 4. ОСНОВНЫЕ PYTHON-ФАЙЛЫ

- whale_detector.py
  status: ACTIVE
  updated: 2026-03-26
  task: TRD-426
  note: tier thresholds fixed

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
  updated: 2026-03-26
  task: SYS-601-FIX
  note: roundtrip jobs disabled (duplicates container)

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
  updated: 2026-03-23
  task: TRD-406
  note: trigger active

- paper_trades → trades
  status: FROZEN
  updated: 2026-03-23
  task: SYS-326
  note: disabled

- settlement pipeline
  status: IN_WORK
  updated: 2026-03-26
  task: ARC-502-C
  note: CLOB API settlement working, need full run for all markets

- whales P&L pipeline
  status: OK
  updated: 2026-03-26
  task: ARC-502-D
  note: Исправлен UPDATE в _update_whales_pnl — теперь использует wallet_address вместо whale_id
  docker_fix: 2026-03-26 — исправлен баг print() в _update_whales_pnl(), пересобран Docker образ

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

- PROJECT_CHANGELOG.md
  status: OK
  updated: 2026-03-25
  task: ARC-502-B
  note: main changelog


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

### 2026-03-26

snapshot_date: 2026-03-26
database: polymarket
schema: public

whales_rows: 0
whale_trades_rows: 8963
paper_trades_rows: 736
paper_trade_notifications_rows: 528
trades_rows: 42
bankroll_rows: 14

whale_trades_last_24h: 767
paper_trades_last_24h: 2
notifications_last_24h: 0

conversion_whale_to_paper_48h: 0.48%
conversion_paper_to_notifications_48h: 0.0%

stale_tables_24h:
- paper_trade_notifications
- trades
- bankroll

notes:
- bankroll contains only test data
- trades table contains only virtual test trades

<!-- END AUTO-GENERATED -->

### 2026-03-25

snapshot_date: 2026-03-25
database: polymarket
schema: public

whales_rows: 0
whale_trades_rows: 8159
paper_trades_rows: 733
paper_trade_notifications_rows: 528
trades_rows: 42
bankroll_rows: 14

whale_trades_last_24h: 473
paper_trades_last_24h: 3
notifications_last_24h: 0

conversion_whale_to_paper_48h: 0.6%
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

## 10. НЕДАВНИЕ ИСПРАВЛЕНИЯ

- ARC-502-D: Исправлен баг обновления P&L китов — UPDATE теперь использует wallet_address вместо whale_id
- SYS-601-FIX: Устранено дублирование roundtrip jobs (main.py → roundtrip_builder container), увеличен интервал до 2h, отключен broken paper_settlement сервис
