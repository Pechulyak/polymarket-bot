# TASK_BOARD

> Единственный source of truth для статусов и списка задач проекта.
> Обновляется STRATEGY. Roo выполняет задачи через TASK PACK.

---

### TRD-402: Fix trades field population in execution pipeline
**Status:** TODO  
**Goals:**
- populate size correctly
- populate opportunity_id from paper_trades
- populate market_title
- fix gas cost units
- ensure new VIRTUAL trades are analytically valid

---

## PHASE 1 — PIPELINE REFACTORING

| ID | Задача | Статус |
|----|--------|--------|
| PHASE1-001 | WhaleTradesRepo — единая точка записи whale_trades | DONE |
| PHASE1-002 | Переключение whale_detector.py на repo | DONE |
| PHASE1-003 | Переключение whale_tracker.py на repo | DONE |
| PHASE1-004 | Pipeline Monitor + Telegram алерты | DONE |
| PHASE1-005 | Финальная верификация Фазы 1 (24ч) | DONE |

---

## PHASE 2 — PIPELINE REFACTORING

### PHASE 2A — Unified Writer (whale_trades)

| ID | Задача | Статус |
|----|--------|--------|
| PHASE2A-001 | Аудит: найти все пути записи в whale_trades | DONE |
| PHASE2A-002 | Переключение virtual_bankroll.py на WhaleTradesRepo | DONE |
| PHASE2A-003 | Переключение whale_poller.py на WhaleTradesRepo | DONE |
| PHASE2A-004 | Deprecation whale_trade_writer.py + очистка мёртвых импортов | DONE |
| PHASE2A-005 | Аудит и удаление deprecated whale_trade_writer | IN_PROGRESS |

### PHASE 2B — Unified Writer (paper_trades)

| ID | Задача | Статус |
|----|--------|--------|
| PHASE2B-001 | Аудит: найти все пути записи в paper_trades | DONE |
| PHASE2B-002 | Отключение VirtualBankroll paper-trade loop в main.py | DONE |
| PHASE2B-003 | Создание PaperTradesRepo (единая точка записи) | DONE |
| PHASE2B-004 | Переключение модулей на PaperTradesRepo | TODO |
| PHASE2B-005 | Создание DB trigger: whale_trades → paper_trades | IN_PROGRESS |
| PHASE2B-006 | Удаление ручного копирования | TODO |

---

## EPIC 1 — WHALE COPY STRATEGY

| ID | Задача | Статус |
|----|--------|--------|
| W-001 | Whale Detection Pipeline | TODO |
| W-002 | Whale Tracking Database | TODO |
| W-003 | Strategy Metrics Engine | TODO |
| W-004 | Copy Trading Engine Integration | TODO |
| WHALE-701 | Whale Classification & Exclusion | DONE |
| BUG-607 | Fix whale re-discovery overwriting excluded status | DONE |

---

## EPIC 2 — ARBITRAGE SYSTEM

| ID | Задача | Статус |
|----|--------|--------|
| A-101 | Cross-Exchange Arbitrage Detector | TODO |
| A-102 | Bybit Hedging Integration | TODO |
| A-103 | Order Book Inefficiency Scanner | TODO |

---

## EPIC 3 — SMART MONEY

| ID | Задача | Статус |
|----|--------|--------|
| S-201 | Kill Switch Mechanisms | TODO |
| S-202 | Position Limits & Drawdown Controls | TODO |
| S-203 | Commission & Fee Tracker | TODO |

---

## EPIC 4 — DATA AUDIT & SCHEMA FIXES (PHASE 4)

| ID | Задача | Статус |
|----|--------|--------|
| PHASE4-001 | Data Audit: schema, JOINs, PnL formulas | DONE |
| Description: Audit completed. Report: docs/audit/PHASE4-001-summary.md. Findings: 100% match rate post-Kelly filter, working JOIN logic, 3 schema issues identified. |
| PHASE4-002 | Add status column to paper_trades table | CANCELLED |
| Description: Not needed — position tracking uses roundtrips table instead. |
| PHASE4-003 | Fix JOIN disambiguation for paper_trades ↔ roundtrips | DONE |
| Description: Materialized view `paper_portfolio_state` created. DISTINCT ON resolves 1:many (77% of trades had >1 match). Final: initial_bankroll=$1000, realized_pnl=-$46.62, current_balance=$953.38, win_rate=41.3%, ROI=-4.66%. Completed: 2026-04-05. |
| PHASE4-004 | Standardize PnL formula to our_pnl_v2 | IN_PROGRESS |
| Description: Two formulas produce different results. Standardize on `our_pnl_v2 = whale_pnl * (kelly_size / whale_size)` for all views. Started: 2026-04-05. |
| PHASE4-005 | Verify Kelly distribution (proportional vs flat) | TODO |
| Description: Currently 97.9% flat $2, 2.1% proportional. Monitor transition. Recommended filter: `created_at > 2026-04-04` |
| SYS-328-AUDIT | File inventory — MD / migrations / Python files | DONE |
| Type: ANALYSIS | Description: Инвентаризация завершена. 44 .md, 13 migration_*.sql (alembic_version НЕ существует), docs/bot_development_kit/04_CODE_LIBRARY — documentation only, мусор НЕ найден. Completed: 2026-04-11. |
| SYS-329 | Log retention policy — journalctl + docker + logrotate | DONE |
| Type: INFRASTRUCTURE | Description: journald 1G/7d + docker json-file 50m×3 + logrotate daily×7. Completed: 2026-04-11. |
| SYS-333 | Fix rsyslog suspend/resume flood | DONE |
| Type: INFRASTRUCTURE | Description: Root cause: missing log files (ufw.log, mail.log, mail.err). Fix: create files with syslog:adm 640. Verified: 0 flood entries/min. Completed: 2026-04-11. |

---

## EPIC 4 — SYSTEM / INFRASTRUCTURE

| ID | Задача | Статус |
|----|--------|--------|
| SYS-322 | PRE-PROD-SECRETS-ROTATION: Ротация секретов перед переключением paper → live | TODO |
| SYS-323 | Docker cleanup — images + build cache | DONE |
| SYS-324 | Очистка системных логов — journalctl + btmp | DONE |
| SYS-325 | Container logs — truncate + настройка ротации | DONE |
| **SYS-326** | **Project cleanup — logs + pycache + backups** | **DONE** |
| SYS-500 | Whale Roundtrip Reconstructor | IN_PROGRESS |

### PRE-PROD-SECRETS-ROTATION: Ротация секретов перед переходом на live

**Status:** TODO
**Приоритет:** 🔴 БЛОКЕР для перехода paper → live
**Создана:** 2026-04-10
**Контекст:** Скомпрометированы в scrollback во время INFRA-002-005.2 (команда `docker compose config | grep -A 15` вывела блок environment в stdout). Решение STRATEGY на 2026-04-10: ротацию отложить до pre-prod, риск принят (paper trading, порт закрыт, нет финансового impact).

**Скомпрометированные секреты:**
- BUILDER_API_KEY (Polymarket CLOB) — 🔴 финансовый impact в live
- BUILDER_API_SECRET (Polymarket CLOB) — 🔴 финансовый impact в live
- BUILDER_PASSPHRASE (Polymarket CLOB) — 🔴 финансовый impact в live
- GRAFANA_DB_PASSWORD (PostgreSQL grafana_reader) — read-only, низкий impact
- ORDER_EXECUTOR_DB_PASSWORD (PostgreSQL order_executor) — limited writer, средний impact

**Goals:**
- Запросить новые BUILDER_* ключи через Polymarket UI/API
- Подтвердить отзыв старых BUILDER_* ключей на стороне Polymarket
- Ротировать GRAFANA_DB_PASSWORD через `ALTER USER grafana_reader`
- Ротировать ORDER_EXECUTOR_DB_PASSWORD через `ALTER USER order_executor`
- Обновить `.env` через heredoc (не sed -i, не echo в stdout)
- Recreate всех контейнеров, читающих обновлённые переменные
- Smoke test: bot успешно аутентифицирован в CLOB, БД-подключения с Сервера 2 работают
- Проверка `.env` после ротации: permissions 600, owner корректен

**Pre-conditions для запуска задачи:**
- Принято решение о переходе на live trading
- Изучена процедура ротации BUILDER_* на стороне Polymarket (есть ли API revoke, lead time, grace period)
- Готов rollback план: старые ключи сохранены в защищённом месте до подтверждения работы новых

**Definition of Done:**
- Все 5 секретов имеют новые значения в `.env`
- Старые BUILDER_* ключи отозваны на стороне Polymarket (подтверждение)
- Контейнеры healthy, smoke_test PASS
- Запись в errors-log о закрытии долга
- Запись в PROJECT_STATE.md о смене статуса безопасности

---

## EPIC 5 — STRATEGY / RESEARCH

| ID | Задача | Статус |
|----|--------|--------|
| STRAT-701 | Запуск paper-trade pipeline для отобранных китов | READY |
| Type: STAGING | Priority: HIGH | |
| Selected: 0x32ed... (WR 81.8%, +$6,599, 11 roundtrips) | 0xd48a... (WR 87.5%, +$1,726, 8 roundtrips) | |
| SYS-325 | Paper Trade Quality Audit (High Price Entries) | READY |

---

## EPIC 6 — SECURITY

| ID | Задача | Статус |
|----|--------|--------|
| SEC-401 | Full Security Audit (ports, env exposure, docker, firewall) | DONE |
| SEC-402 | Verify No Public Ports Policy enforcement | DONE |
| SEC-403 | Scan server for exposed services and vulnerabilities | DONE |
| SEC-404 | Restrict Qdrant to localhost only | DONE |

---

## EPIC 7 — SYSTEM HYGIENE

| ID | Задача | Статус |
|----|--------|--------|
| SYS-401 | Project cleanup (logs, temp files, unused scripts) | READY |
| SYS-402 | Remove unused docker images and dangling volumes | TODO |
| SYS-403 | Verify .env permissions and secret handling | TODO |
| SYS-500 | Whale Roundtrip Reconstructor | IN_PROGRESS |

Description: Интегрирован в main.py. Проверка закрытия позиций за сегодня.

| SYS-601-FIX | Fix дублирование roundtrip_builder + broken paper_settlement | IN_PROGRESS |
| DOC-601 | Аудит PROJECT_STATE.md на соответствие governance | DONE |

---

## EPIC 8 — TRADING CORRECTNESS

| ID | Задача | Статус |
|----|--------|--------|
| BUG-701 | Fix days_active column reference (should be days_active_7d) | DONE |
| Описание: Исправлено в refresh_qualification() и update_whale_activity_counters() — заменены все SQL-ссылки w.days_active на w.days_active_7d. Колонка days_active удалена из БД миграцией ARC-501. whale-detector перезапущен, ошибок нет. |
| TRD-401 | Audit trades table integrity | IN_PROGRESS |
Description: Audit correctness of trades table generated by paper trading pipeline.
Goals:
- validate trades data integrity
- detect zero-size trades
- verify PnL fields
- verify gas cost values
- check market metadata completeness
| TRD-402 | Fix trades field population in execution pipeline | TODO |
| TRD-403 | Verify settlement behaviour (sell vs event resolution) | TODO |
| TRD-404 | Verify bankroll accounting (entry/exit updates) | TODO |
| FIN-401 | Fix virtual bankroll flow across trade lifecycle | TODO |
Description: Fix virtual bankroll logic so that capital is blocked only on executed trade open and returned only on trade close.
Goals:
- ensure paper_trades do not affect bankroll
- ensure trades(open) reduce available and increase allocated
- ensure trades(closed) release allocated capital
- ensure net_pnl is reflected in bankroll correctly
| TRD-405 | Verify Kelly sizing logic | DONE |
| TRD-406 | Fix zero-size paper trades on open path | TODO |
| TRD-407 | Investigate execution gap (paper_trades vs trades) | TODO |
| TRD-408 | Fix traded_at to use API timestamp instead of NOW() | DONE |
Description: Removed get_market_category HTTP call from hot path in whale_detector.py, whale_tracker.py, virtual_bankroll.py. Commits: cefb92a, dbe310f. |
| TRD-409 | Fix settlement integration with VirtualBankroll | DONE |
Description: Completed (details in PROJECT_STATE)
| TRD-411 | Audit whale exit handling and buy/sell event recording across pipeline | DONE |
Description: Completed (details in PROJECT_STATE)
| TRD-412 | Create whale_trade_roundtrips table and implement whale position reconstruction logic | TODO |
Description: Introduce a new analytical layer that reconstructs whale positions (round-trips) from the event-level table `whale_trades`.
Goals:
- Create new table `whale_trade_roundtrips` - Store reconstructed whale positions (not individual trades)
- Implement position reconstruction logic - Build positions from whale_trades, detect open/close/flip/partial close
- Implement PnL calculation at position level - Calculate gross and net PnL only when close is reliably determined
- Reuse existing logic where possible - Check if algorithm already exists before implementing
- Add market context - Include market_title and market_category
- Perform historical backfill - Reconstruct positions for existing whale_trades
- Ensure analytical correctness - Do not depend on paper_trades or trades |
| ARC-502-B | Fuzzy matching close for short selling (+27 CLOSED) | DONE |
Description: Fixed fuzzy matching close logic. Previously, SELL events for short positions weren't matched to OPEN roundtrips due to strict market_id + outcome matching. Added fuzzy matching: when no exact close found, fall back to matching by market_id only. Result: +27 roundtrips closed.
| TRD-413 | Audit whale_trades ingestion completeness for tracked whales | TODO |
Description: Whale trades ingestion incomplete (~99% loss for some whales). Root cause: global 500-trade limit + no per-wallet backfill. Audit completed, awaiting fix.
| TRD-421 | Аудит whale_trades — Завершён | DONE |
Description: Completed (details in PROJECT_STATE)
| BUG-603 | Fix dedup filter paper_trades→trades + bankroll reset $1000 | DONE |
Description: Дедупликация по market_id+whale+side блокировала новые trades. Переход на opportunity_id = paper_{id}. Bankroll reset to $1000.
| BUG-504 | Fix false new_trades counter in whale_detector logs | DONE |
Description: save_whale_trade now returns bool based on rowcount (ON CONFLICT DO NOTHING). Fixed new_trades showing 50 when only new inserts counted.
| TRD-422 | Добавить market_category в whale_trades и унифицировать запись | DONE |
Description: Completed (details in PROJECT_STATE)
| TRD-426 | Fix tier пороги — 97% HOT | DONE |
Description: Fixed tier thresholds (HOT: 1d, WARM: 7d). Recalculated tiers in DB (HOT: 40.7%, WARM: 59%, COLD: 0.3%). whale-detector restarted and running.
| TRD-427 | Fix: OPEN roundtrips не обновляются settlement (757 stuck) | DONE |
Description: Fixed by adding --settle to roundtrip_builder in docker-compose.yml. Now runs --settle every 2 hours.
| TRD-420-A | Per-wallet polling для copy_status='paper' китов | DONE |
Description: Targeted fetch trades для китов с copy_status='paper' каждые 30 сек. Работает: 148 whale_trades + 84 paper_trades за 5 минут.
Разблокирует STRAT-701 paper-trade pipeline.
| TRD-420-B | Per-wallet polling для copy_status='tracked' китов (5 мин) | IN_PROGRESS |
Description: Targeted fetch trades для tracked китов. Только сбор данных в whale_trades, без paper_trades.
| TRD-430 | Аудит paper trading pipeline: trades → settlement → bankroll | DONE |
Description: Аудит завершён. Timezone hypothesis rejected — pipeline работает корректно. Результат: 459 trades закрыты через CLOB API, bankroll восстанавливается из БД, дедупликация по opportunity_id.
| BUG-601 | Diagnose settlement failure — 0 closed trades with resolved markets | DONE |
| BUG-601-FIX | Switch settlement engine from Gamma API to CLOB API | DONE |
Description: Settlement использовал Gamma API (422 error). Переключение на CLOB API `/markets/{market_id}` для корректного получения resolution data. Результат: 459 trades закрыты. |
| BUG-604 | Bankroll reconciliation after settlement + fix event loop | DONE |
Description: Settlement не обновляет VirtualBankroll (event loop conflict). Добавить reconciliation из trades table. Реализовано: reconcile_from_trades() в virtual_bankroll.py, вызывается при старте и после каждого settlement цикла. Удалён дублирующий _save_bankroll_history из load_open_positions_from_db(). Результат: bankroll консистентный - $909.19 (initial $1000 - $90.80 P&L), 485 open, 459 closed, 50.3% win rate.

---

## EPIC 9 — DATA INTEGRITY

| ID | Задача | Статус |
|----|--------|--------|
| TRD-414 | Backup whales and whale_trades + snapshot report | DONE |
| TRD-415 | Freeze whale discovery and whale_trades writes before cleanup | DONE |
| TRD-416 | Reduce whales universe to qualified subset and clean whale_trades | DONE |
| TRD-417 | Audit API response structure across market types before whales schema redesign | TODO |
| TRD-418 | Transform whales table schema to approved activity-based structure | DONE |
| TRD-419 | Migrate whales logic from legacy fields to new activity-based fields | DONE |
| ARC-503 | Remove legacy fields is_winner and profit_usd from whale_trades | DONE |
| TRD-420 | Рефакторинг whale discovery: initial history aggregation + tiered polling | IN_PROGRESS |
Description: Refactor whale discovery logic. See PROJECT_STATE for details.
| DATA-404 | Reset virtual bankroll for fresh paper trading cycle | DONE |
| DATA-405 | Cleanup test records from database | DONE |

---

## EPIC 10 — ANALYTICS PREPARATION

| ID | Задача | Статус |
|----|--------|--------|
| ANA-401 | Extend trades table with market categories | TODO |
| ANA-402 | Integrate Polymarket /categories endpoint | TODO |
| ANA-403 | Whale behaviour analysis by category | TODO |
| ANA-404 | Whale behaviour analysis by entry price (≥0.95, ≤0.05) | TODO |

---

## EPIC 11 — DATA LIFECYCLE

| ID | Задача | Статус |
|----|--------|--------|
| ARC-502-A | Roundtrip Builder — создание OPEN roundtrips из BUY событий | DONE |
| ARC-502-B | Roundtrip Builder — закрытие позиций через SELL события | DONE |
| ARC-502-C | Roundtrip Builder — settlement через Gamma API | DONE |

Description: Implemented settlement via CLOB API. Uses GET /markets/{conditionId} to get closed market data with winner status. Tested on 4 closed markets - 23 roundtrips settled successfully. Matching method: SETTLEMENT, close_type: SETTLEMENT_WIN/SETTLEMENT_LOSS.
| ARC-502-D | Fix: whale_trade_roundtrips → whales P&L обновление | DONE |

Description: Completed. Roundtrip builder now updates whales table with P&L from closed positions.

---

## EPIC 11 — PROPORTIONAL KELLY SIZING (Phase 1.5)

| ID | Задача | Статус |
|----|--------|--------|
| PHASE1.5-001 | Аудит текущего Kelly sizing в trigger | DONE |
| PHASE1.5-002 | strategy_config + estimated_capital schema | DONE |
| PHASE1.5-003 | Обновление trigger — proportional sizing | DONE |
| PHASE1.5-004 | Установка estimated_capital для paper кита | DONE |
| PHASE1.5-005 | Верификация полного pipeline | DONE |

---

## PHASE 3 — SETTLEMENT В БД

| ID | Задача | Статус |
|----|--------|--------|
| PHASE3-001 | Аудит текущего settlement в roundtrip_builder | DONE |
| PHASE3-002 | Определить API endpoint для resolution data | DONE |
| PHASE3-003 | Спроектировать market_resolutions таблицу | DONE |
| PHASE3-004 | Перенести settlement логику в БД (trigger/procedure) | DONE |
| PHASE3-005 | Обновить roundtrip_builder.py → использовать БД | DONE |
| PHASE3-006 | Удалить HTTP settlement из roundtrip_builder | DONE |
| PHASE3-007 | Верификация end-to-end | IN_PROGRESS |
Description: Ручной запуск 09:33 UTC — ✅ УСПЕШНО. Результаты: 2189 китов обновлено, market_resolutions populated. Сравнение с cron 10:00 UTC pending.

---

## PHASE 4 — MATERIALIZED VIEWS + DYNAMIC KELLY

| ID | Задача | Статус |
|----|--------|--------|
| PHASE4-001 | Аудит данных для views (схемы, связи, match rate) | DONE |
| PHASE4-002 | View: whale_pnl_summary | DONE |
| PHASE4-003 | View: paper_portfolio_state | DONE |
| PHASE4-004 | View: paper_simulation_pnl | DONE |
| Description: Created materialized view with standardized PnL formula (our_pnl_v2 = whale_pnl * kelly_ratio). Validated against cross-check queries. Final: initial_bankroll=$1000, realized_pnl=-$46.62, current_balance=$953.38. Completed: 2026-04-05. |
| PHASE4-005 | Cron refresh views + smoke_test checks | DONE |
| Description: Created refresh_views.sh, added cron (15 */2 * * *), added 3 view checks to smoke_test.sh. All 23 checks pass. Completed: 2026-04-05. |
| PHASE4-006 | Dynamic Kelly — trigger берёт bankroll из view | DONE |
| Description: Trigger modified to use dynamic bankroll from paper_portfolio_state view. Config key kelly_bankroll_source=1 enables dynamic mode. Fallback: view → strategy_config → $1000. Verified: Dynamic ($1.19) vs Static ($1.25), Δ=-4.66%. Completed: 2026-04-05. |
| PHASE4-007 | Финальная верификация Фазы 4 | DONE |

---

## INFRASTRUCTURE

| ID | Задача | Статус |
|----|--------|--------|
| INFRA-002-001 | Аудит текущей конфигурации безопасности PostgreSQL и сети (Сервер 1) | DONE |
| INFRA-002-002 | Создание read-only PostgreSQL user для Grafana (grafana_reader) | DONE |
| INFRA-002-003 | Создание PostgreSQL user order_executor для будущего live trading (Фаза 5) | DONE |
| INFRA-002-004.1 | Baseline перед INFRA-002-004 retry | DONE |
| INFRA-002-004.2 | Аудит pg_hba.conf — создание users и настройка trust | DONE |
| INFRA-002-004.3 | Подготовить новый pg_hba.conf файл (БЕЗ применения) | DONE |
| INFRA-002-004.4 | Применить pg_hba.conf через docker cp + pg_reload_conf | DONE |
| Type: INFRASTRUCTURE | Description: Скопировать pg_hba.conf.new в контейнер, выполнить pg_reload_conf(), проверить smoke_test | |
| INFRA-002-005.1 | Сгенерировать self-signed SSL сертификат для PostgreSQL (CA-режим для verify-ca) | DONE |
| INFRA-002-005.2 | Включить SSL в PostgreSQL через command: в docker-compose (вариант A) | DONE |
| Type: INFRASTRUCTURE | Description: Добавлен mount config/ssl/ + SSL параметры в command, force-recreate postgres. Верификация: SHOW ssl=on, pg_stat_ssl.ssl=t, smoke_test 23/23 | |
| INFRA-002-005.3 | Заменить host → hostssl в pg_hba.conf для grafana_reader и order_executor | DONE |
| Type: INFRASTRUCTURE | Description: pg_ctl reload + force-recreate (mount был сломан). Верификация: pg_hba_file_rules type=hostssl, MD5 совпадает, smoke_test 23/23 | |
| INFRA-002-006.0a | Pre-flight audit — найти все места использования POSTGRES_PASSWORD | DONE |
| INFRA-002-006.0b | Сменить POSTGRES_PASSWORD с Artem15 на сильный | DONE |
| Type: CRITICAL | Description: Audit + rotation completed. Пароль ротирован, containers recreated, smoke_test 23/23, whale_trades pipeline verified. | |
| INFRA-002-006.FIREWALL | Firewall hardening — закрыть порт 5433 для всех кроме 62.60.233.100 | DONE |
| Type: INFRASTRUCTURE/SECURITY | Description: Docker DNAT обходит INPUT и ufw. Решение: DOCKER-USER chain + `-m conntrack --ctorigdstport 5433`. Правила: ESTABLISHED/RELATED ACCEPT → whitelist 62.60.233.100 ACCEPT → DROP. Верификация: позитивный тест с Сервера 2 OK, негативный с Windows timeout. | |
| INFRA-002-006.1b | Firewall persistence — systemd unit для DOCKER-USER правил | DONE |
| Type: INFRASTRUCTURE | Description: /etc/systemd/system/docker-firewall-rules.service. Idempotent cleanup loop + 3 ExecStart. Enabled on boot. netfilter-persistent disabled для избежания конфликта. | |
| INFRA-002-007 | Тест полного подключения с Сервера 2 (psql + grafana_reader/order_executor + SSL) | DONE |
| Type: VERIFICATION | Description: grafana_reader SSL TLSv1.3 AES-256-GCM, SELECT OK, writes denied. Grafana data source на stat.pecha.website настроен, Save & Test OK. order_executor — коннект работает, но права только SELECT на 5 таблицах (заведено INFRA-002-AUDIT-ORDER-EXEC). | |
| INFRA-002-008 | Финальный security baseline audit эпика INFRA-002 | DONE |
| Type: AUDIT | Description: 9-этапный read-only аудит. Результат: docs/INFRA-002-SECURITY-BASELINE.md. Network/SSL/pg_hba/Roles/Secrets — PASS. Logging/Backups/Host hardening/Docs — gaps, заведены отдельные задачи. | |
| INFRA-002-AUDIT-ORDER-EXEC | Audit order_executor permissions — только SELECT на 5 таблицах, нет write, нет pending_orders schema | TODO |
| Type: AUDIT/SECURITY | Description: Обнаружено при INFRA-002-007 верификации. Блокирует live order execution, не блокирует Grafana. | |
| INFRA-003-BACKUP-POLICY | Automated pg_dump + off-site + encryption + retention + restore test | TODO |
| Type: CRITICAL/INFRASTRUCTURE | Description: Нет автоматического backup. Блокирует live execution. | |
| SEC-501-HOST-HARDENING | SSH hardening (PasswordAuth=no, PermitRootLogin, fail2ban) | TODO |
| Type: CRITICAL/SECURITY | Description: SSH имеет gaps: PermitRootLogin=yes, PasswordAuthentication=yes, no fail2ban. Обход network security -> shell -> .env -> full DB access. | |
| postgres-logging-hardening | Enable log_connections/disconnections, расширить log_line_prefix | TODO |
| Type: LOW/INFRASTRUCTURE | Description: log_connections=off, log_disconnections=off, minimal observability. | |
| firewall-startup-race-fix | Устранить окно незащищённости между docker start и firewall unit | TODO |
| Type: LOW/INFRASTRUCTURE | Description: Startup race window ~seconds, pg_hba reject компенсирует. | |
| user-provisioning-runbook | Runbook для добавления нового DB user | TODO |
| Type: LOW/DOCUMENTATION | Description: Процедура добавления user описана в pg_hba.conf комментариях, отдельный runbook отсутствует. | |

---

## SYSTEM TASKS

| ID | Задача | Статус |
|----|--------|--------|
| SYS-501 | Project Filesystem Cleanup (logs, temp, md artifacts) | DONE |

---

*Обновлено: 2026-04-11*
