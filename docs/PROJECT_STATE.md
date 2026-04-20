# СОСТОЯНИЕ ПРОЕКТА

Обновлено: 2026-04-19
Версия: v2_clean  
Фаза: Paper trading (edge validation)

---

## 1. РЕЖИМ ПРОЕКТА
-Активные стратегии:
- Whale Copy: IN_WORK
- Arbitrage: FROZEN
- Anomaly Detection: FROZEN

- Режим торговли
  status: OK
  updated: 2026-04-19
  task: 
  note: paper active

- Режим наблюдения
  status: OK
  updated: 2026-04-19
  task: 
  note: downstream off

- Trading Metrics (цели выхода в live)
  status: IN_WORK
  updated: 2026-04-19
  task: 
  note: targets defined

  target_roi: 25%
  target_winrate: >60%
  target_drawdown: controlled

## Risk-contour (Kelly)
- status: OK
- updated: 2026-04-19
- task: PIPE-029, PIPE-030
- note: dynamic kelly, bankroll via view

- Edge статус
  status: IN_WORK
  updated: 2026-03-23
  task: 
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
  updated: 2026-04-19
  task: TRD-439
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
  task: DATA-406
  note: legacy fields removed

- Таблица paper_trades
  status: OK
  updated: 2026-03-29
  task: TRD-439
  note: unfrozen, filtered by copy_status='paper'

- Таблица trades
  status: OK
  updated: 2026-03-29
  task: TRD-439
  note: unfrozen

- Таблица whale_trade_roundtrips
  status: OK
  updated: 2026-03-26
  task: PIPE-038
  note: settlement via CLOB API working

- Таблица bankroll
  status: OK
  updated: 2026-03-29
  task: TRD-439
  note: reset to $100, unfrozen

---

## Materialized Views

### whale_pnl_summary (materialized)
- status: OK
- updated: 2026-04-05
- task: PIPE-024
- note: aggregated P&L per whale, refresh 2h

### paper_portfolio_state (materialized)
- status: OK
- updated: 2026-04-05
- task: PIPE-030
- note: dynamic filter via bankroll_reset_at

### paper_simulation_pnl (materialized)
- status: OK
- updated: 2026-04-05
- task: PIPE-030
- note: trade-by-trade paper P&L

---

## Bankroll Reset
- mechanism: bankroll_reset_at in strategy_config (unix timestamp)
- next_reset: manual via strategy_config update

---

## 3. КОНТЕЙНЕРЫ

- postgres
  status: OK
  updated: 2026-03-23
  task: 
  note: running

- redis
  status: OK
  updated: 2026-03-23
  task: 
  note: running

- whale_detector
  status: ACTIVE
  updated: 2026-04-02
  task: TRD-434
  note: paper+tracked polling, duplicate detection fixed

- bot (main)
  status: PARTIAL
  updated: 2026-03-23
  task: 
  note: no execution

- roundtrip_builder
  status: OK
  updated: 2026-04-18
  task: PIPE-041
  note: standalone container, healthy, settlement via cron script

- paper_settlement
  status: DEPRECATED
  updated: 2026-04-18
  task: PIPE-041
  note: disabled in main.py, replaced by roundtrip_builder

---

## 4. ОСНОВНЫЕ PYTHON-ФАЙЛЫ

- whale_detector.py
  status: ACTIVE
  updated: 2026-04-02
  task: PIPE-002
  note: записи через WhaleTradesRepo

- whale_tracker.py
  status: OK
  updated: 2026-04-02
  task: PIPE-003
  note: save_whale_trade через WhaleTradesRepo

- whale_trade_writer.py
  status: DEPRECATED
  updated: 2026-04-02
  task: PIPE-009
  note: заменён WhaleTradesRepo

- virtual_bankroll.py
  status: FROZEN
  updated: 2026-03-23
  task: 
  note: disabled

- main.py
  status: PARTIAL
  updated: 2026-03-26
  task: 
  note: roundtrip jobs disabled (duplicates container)

- copy_trading_engine.py
  status: FROZEN
  updated: 2026-03-23
  task: 
  note: disabled

- whale_trades_repo.py
  status: OK
  updated: 2026-04-02
  task: PIPE-001
  note: единая точка записи whale_trades

---

## 5. PIPELINE

- Pipeline Phase 1
  status: OK
  updated: 2026-04-03
  task: PIPE-005
  note: 24h verified, repo active, monitor running

- Daily Whale Alert Monitor
  status: OK
  updated: 2026-04-16
  task: ANA-501
  note: cron 08:00 UTC, Telegram alerts

- Weekly AI whale analysis
  status: ACTIVE
  updated: 2026-04-19
  task: ANA-502
  note: cron weekly, Telegram recommendations

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

- whale_trades → paper_trades
  status: OK
  updated: 2026-03-30
  task: 
  note: real-time verified, paper whales

- paper_trades → trades
  status: OK
  updated: 2026-03-29
  task: TRD-439
  note: unfrozen

- settlement pipeline
  status: OK
  updated: 2026-04-05
  task: PIPE-023
  note: settlement via cron script, resolved markets closed automatically

- smoke_test.sh
  status: OK
  updated: 2026-04-14
  task: 
  note: all checks passing

- whales P&L pipeline
  status: OK
  updated: 2026-03-26
  task: PIPE-039

- market_category backfill
  status: OK
  updated: 2026-04-12
  task: 
  note: whale_trades + roundtrips

- notifications pipeline
  status: OK
  updated: 2026-03-29
  task: TRD-439
  note: unfrozen

- pipeline_monitor
  status: ACTIVE
  updated: 2026-04-02
  task: PIPE-004
  note: cron */30, Telegram alerts every 30min

- Paper-trade pipeline (active whales)
  status: ACTIVE
  updated: 2026-04-19
  task: TRD-439
  note: edge validation phase

- Tracked polling loop
  status: ACTIVE
  updated: 2026-04-19
  task: TRD-420-B
  note: per-wallet, 5min interval

---

## WHALE COPY SELECTION

- P&L Gate
  status: ACTIVE
  updated: 2026-03-29
  task: TRD-439
  note: min 5 roundtrips, WR ≥60%, PnL >$0, tier HOT/WARM

- Kelly Sizing
  status: OK
  updated: 2026-04-04
  task: PIPE-035
  note: proportional sizing, strategy_config driven

- Selected Whales
  status: PAPER
  updated: 2026-03-30
  task: 
  note: paper whales selected via P&L Gate, managed by STRATEGY

---

## 6. БЕЗОПАСНОСТЬ

- SSH hardening
  status: DONE
  updated: 2026-04-12
  task: SEC-501
  note: PasswordAuth=no, PermitRootLogin=prohibit-password, fail2ban active

- Публичные порты
  status: OK
  updated: 2026-03-23
  task: 
  note: internal only

- Доступ к БД
  status: OK
  updated: 2026-03-23
  task: 
  note: docker network

- Backups
  status: OK
  updated: 2026-04-12
  task: INFRA-018
  note: daily encrypted B2, retention 7d, Telegram alert

- .env доступ
  status: OK
  updated: 2026-03-23
  task: 
  note: restricted

---

## 7. АКТИВНЫЕ БЛОКЕРЫ

none

---

## 8. ДОКУМЕНТАЦИЯ

- init_db.sql
  status: OK
  updated: 2026-04-19
  task: 
  note: 17 tables, schema matches DB

- TASK_BOARD.md
  status: OK
  updated: 2026-04-19
  task: HYG-009
  note: refactored to 3 LANE + 9 EPIC, 139 tasks

- PROJECT_STATE.md
  status: OK
  updated: 2026-04-19
  task: DOC-603
  note: updated

- CHAT GOVERNANCE.md
  status: OK
  updated: 2026-04-19
  task: DOC-GOVERNANCE-UPDATE
  note: supplemented with rules 6-11

- PROJECT_STATE_GOVERNANCE.md
  status: OK
  updated: 2026-04-19
  task: 
  note: governance rules

- WHALE_STATUS_TRANSITIONS.md
  status: ACTIVE
  updated: 2026-04-20
  task: WHALE-STATUS-TRANSITION-SPEC
  note: governance spec v1.0 для copy_status transitions (none ↔ tracked ↔ paper ↔ excluded). Формула estimated_capital: max_daily_volume_30d.

- PROJECT_CHANGELOG.md
  status: OK
  updated: 2026-04-19
  task: 
  note: main changelog
