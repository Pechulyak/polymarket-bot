# TASK_BOARD

> Единственный source of truth для статусов и списка задач проекта.
> Обновляется STRATEGY. Roo выполняет задачи через TASK PACK.

---

| TRD-402 | Исправление заполнения полей trades в execution pipeline | TODO |

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
| PHASE2A-005 | Аудит и удаление deprecated whale_trade_writer | DONE |

### PHASE 2B — Unified Writer (paper_trades)

| ID | Задача | Статус |
|----|--------|--------|
| PHASE2B-001 | Аудит: найти все пути записи в paper_trades | DONE |
| PHASE2B-002 | Отключение VirtualBankroll paper-trade loop в main.py | DONE |
| PHASE2B-003 | Создание PaperTradesRepo (единая точка записи) | DONE |
| PHASE2B-004 | Переключение модулей на PaperTradesRepo | DONE |
| PHASE2B-005 | Создание DB trigger: whale_trades → paper_trades | DONE |
| PHASE2B-006 | Удаление ручного копирования | DONE |

---

## EPIC 1 — WHALE COPY STRATEGY

| ID | Задача | Статус |
|----|--------|--------|
| W-001 | Обнаружение китов — pipeline | DONE |
| W-002 | База данных китов — единая точка записи | DONE |
| W-003 | Движок метрик стратегии (Kelly + views) | DONE |
| W-004 | Интеграция copy-trading engine | FROZEN |
| WHALE-701 | Классификация и исключение китов | DONE |
| BUG-607 | Исправление: re-discovery перезаписывает excluded-статус | DONE |

---

## EPIC 2 — ARBITRAGE SYSTEM

| ID | Задача | Статус |
|----|--------|--------|
| A-101 | Обнаружение кросс-биржевого арбитража | TODO |
| A-102 | Интеграция хеджирования Bybit | TODO |
| A-103 | Сканер неэффективностей книги заказов | TODO |

---

## EPIC 3 — SMART MONEY

| ID | Задача | Статус |
|----|--------|--------|
| S-201 | Механизмы Kill Switch | TODO |
| S-202 | Лимиты позиций и контроль просадки | TODO |
| S-203 | Трекер комиссий и сборов | TODO |

---

## EPIC 4 — DATA AUDIT & SCHEMA FIXES (PHASE 4)

| ID | Задача | Статус |
|----|--------|--------|
| PHASE4-001 | Аудит данных: схема, JOINs, формулы PnL | DONE |
| PHASE4-002 | Добавить колонку status в таблицу paper_trades | CANCELLED |
| PHASE4-003 | Исправить JOIN disambiguation для paper_trades ↔ roundtrips | DONE |
| PHASE4-004 | Стандартизировать формулу PnL на our_pnl_v2 | IN_PROGRESS |
| PHASE4-005 | Верификация Kelly распределения (пропорциональное vs плоское) | TODO |
| SYS-328-AUDIT | Инвентаризация файлов — MD / migrations / Python | DONE |
| SYS-329 | Политика хранения логов — journalctl + docker + logrotate | DONE |
| SYS-333 | Исправление rsyslog suspend/resume flood | DONE |
| SYS-334 | Исправление market_category в whale_trade_roundtrips | DONE |
| SYS-335 | Исправление smoke_test.sh — проверки свежести fetch | DONE |
| SYS-336 | Исправление Kelly sizing: минимум $1, максимум 5% bankroll | DONE |
| SEC-501 | SSH Hardening + проверка инцидента 006.1 | DONE |
| SYS-331 | Исправление застрявших roundtrips — 37 OPEN при resolved markets | DONE |

---

## EPIC 4 — SYSTEM / INFRASTRUCTURE

| ID | Задача | Статус |
|----|--------|--------|
| SYS-323 | Docker cleanup — images + build cache | DONE |
| SYS-324 | Очистка системных логов — journalctl + btmp | DONE |
| SYS-325 | Container logs — truncate + настройка ротации | DONE |
| SYS-326 | Project cleanup — logs + pycache + backups | DONE |
| SYS-500 | Whale Roundtrip Reconstructor | DONE |

| SYS-322 | PRE-PROD-SECRETS-ROTATION: Ротация секретов перед переходом на live | TODO |

---

## EPIC 5 — STRATEGY / RESEARCH

| ID | Задача | Статус |
|----|--------|--------|
| STRAT-701 | Запуск paper-trade pipeline для отобранных китов | READY |

---

## EPIC 6 — SECURITY

| ID | Задача | Статус |
|----|--------|--------|
| SEC-401 | Полный Security Audit (порты, env exposure, docker, firewall) | DONE |
| SEC-402 | Проверка политики No Public Ports | DONE |
| SEC-403 | Сканирование сервера на открытые сервисы и уязвимости | DONE |
| SEC-404 | Ограничить Qdrant только localhost | DONE |

---

## EPIC 7 — SYSTEM HYGIENE

| ID | Задача | Статус |
|----|--------|--------|
| SYS-401 | Очистка проекта (логи, temp файлы, неиспользуемые скрипты) | READY |
| SYS-402 | Удалить неиспользуемые docker images и dangling volumes | TODO |
| SYS-403 | Проверить permissions .env и обработку секретов | TODO |
| SYS-601 | Очистка TASK_BOARD и CHANGELOG — унификация формата | DONE |
| SYS-601-FIX | Исправление дублирования roundtrip_builder + broken paper_settlement | DONE |
| DOC-601 | Аудит PROJECT_STATE.md на соответствие governance | DONE |

---

## EPIC 8 — TRADING CORRECTNESS

| ID | Задача | Статус |
|----|--------|--------|
| BUG-701 | Исправление ссылки на days_active (была days_active_7d) | DONE |
| TRD-401 | Аудит целостности таблицы trades | IN_PROGRESS |
| TRD-403 | Верификация поведения settlement (sell vs event resolution) | TODO |
| TRD-404 | Верификация учёта bankroll (entry/exit updates) | TODO |
| FIN-401 | Исправление потока virtual bankroll через lifecycle трейда | TODO |
| TRD-405 | Верификация логики Kelly sizing | DONE |
| TRD-406 | Исправление zero-size paper trades на open path | TODO |
| TRD-407 | Исследование execution gap (paper_trades vs trades) | TODO |
| TRD-408 | Исправление traded_at — использовать API timestamp вместо NOW() | DONE |
| TRD-409 | Исправление интеграции settlement с VirtualBankroll | DONE |
| TRD-411 | Аудит обработки whale exit и записи buy/sell событий | DONE |
| TRD-412 | Создание таблицы whale_trade_roundtrips и логики реконструкции позиций | TODO |
| ARC-502-B | Fuzzy matching close для short selling (+27 CLOSED) | DONE |
| TRD-413 | Аудит полноты ingestion whale_trades для tracked китов | TODO |
| TRD-421 | Аудит whale_trades — Завершён | DONE |
| BUG-603 | Исправление dedup filter paper_trades→trades + bankroll reset | DONE |
| BUG-504 | Исправление false счётчика new_trades в whale_detector logs | DONE |
| TRD-422 | Добавить market_category в whale_trades и унифицировать запись | DONE |
| TRD-426 | Исправление tier порогов — 97% HOT | DONE |
| TRD-427 | Исправление: OPEN roundtrips не обновляются settlement (757 stuck) | DONE |
| TRD-420-A | Per-wallet polling для copy_status='paper' китов | DONE |
| TRD-420-B | Per-wallet polling для copy_status='tracked' китов (5 мин) | IN_PROGRESS |
| TRD-430 | Аудит paper trading pipeline: trades → settlement → bankroll | DONE |
| BUG-601 | Диагностика failure settlement — 0 closed trades с resolved markets | DONE |
| BUG-601-FIX | Переключение settlement engine с Gamma API на CLOB API | DONE |
| BUG-604 | Reconciliation bankroll после settlement + исправление event loop | DONE |
| BUG-801 | Аудит pnl_status UNAVAILABLE в whale_trade_roundtrips | DONE |

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
| DATA-404 | Reset virtual bankroll for fresh paper trading cycle | DONE |
| DATA-405 | Cleanup test records from database | DONE |

---

## EPIC 10 — ANALYTICS PREPARATION

| ID | Задача | Статус |
|----|--------|--------|
| ANA-401 | Расширить таблицу trades категориями рынков | TODO |
| ANA-402 | Интеграция Polymarket /categories endpoint | TODO |
| ANA-403 | Анализ поведения китов по категориям | TODO |
| ANA-404 | Анализ поведения китов по цене входа (≥0.95, ≤0.05) | TODO |
| ANA-501 | Ежедневный мониторинг Whale Alert (Слой 1) | DONE |
| ANA-502 | Еженедельный AI анализ — миграция БД (whale_ai_analysis) | DONE |
| ANA-502-SCRIPT | Реализация скрипта еженедельного AI анализа | IN_PROGRESS |
| ANA-502-CRON | Еженедельный анализ: test run + cron | DONE |
| ANA-502-FIX | Исправление recommendations_json + prompt rules | IN_PROGRESS |
| ANA-502-SQL | SQL-слой: финальные запросы для еженедельного AI-анализа | DONE |

---

## EPIC 11 — DATA LIFECYCLE

| ID | Задача | Статус |
|----|--------|--------|
| ARC-502-A | Roundtrip Builder — создание OPEN roundtrips из BUY событий | DONE |
| ARC-502-B | Roundtrip Builder — закрытие позиций через SELL события | DONE |
| ARC-502-C | Roundtrip Builder — settlement через CLOB API | DONE |
| ARC-502-D | Исправление: whale_trade_roundtrips → whales P&L обновление | DONE |

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

---

## PHASE 4 — MATERIALIZED VIEWS + DYNAMIC KELLY

| ID | Задача | Статус |
|----|--------|--------|
| PHASE4-001 | Аудит данных для views (схемы, связи, match rate) | DONE |
| PHASE4-002 | View: whale_pnl_summary | DONE |
| PHASE4-003 | View: paper_portfolio_state | DONE |
| PHASE4-004 | View: paper_simulation_pnl | DONE |
| PHASE4-005 | Cron refresh views + smoke_test checks | DONE |
| PHASE4-006 | Dynamic Kelly — trigger берёт bankroll из view | DONE |
| PHASE4-007 | Финальная верификация Фазы 4 | DONE |

---

## INFRASTRUCTURE

| ID | Задача | Статус |
|----|--------|--------|
| INFRA-002-001 | Аудит конфигурации безопасности PostgreSQL и сети (Сервер 1) | DONE |
| INFRA-002-002 | Создание read-only PostgreSQL user для Grafana | DONE |
| INFRA-002-003 | Создание PostgreSQL user order_executor для live trading | DONE |
| INFRA-002-004.1 | Baseline перед INFRA-002-004 retry | DONE |
| INFRA-002-004.2 | Аудит pg_hba.conf — создание users и настройка trust | DONE |
| INFRA-002-004.3 | Подготовить новый pg_hba.conf файл (БЕЗ применения) | DONE |
| INFRA-002-004.4 | Применить pg_hba.conf через docker cp + pg_reload_conf | DONE |
| INFRA-002-005.1 | Сгенерировать self-signed SSL сертификат для PostgreSQL | DONE |
| INFRA-002-005.2 | Включить SSL в PostgreSQL через docker-compose | DONE |
| INFRA-002-005.3 | Заменить host → hostssl в pg_hba.conf | DONE |
| INFRA-002-006.0a | Pre-flight audit — найти использования POSTGRES_PASSWORD | DONE |
| INFRA-002-006.0b | Сменить POSTGRES_PASSWORD на сильный | DONE |
| INFRA-002-006.FIREWALL | Firewall hardening — закрыть порт 5433 для всех кроме 62.60.233.100 | DONE |
| INFRA-002-006.1b | Firewall persistence — systemd unit для DOCKER-USER правил | DONE |
| INFRA-002-007 | Тест полного подключения с Сервера 2 | DONE |
| INFRA-002-008 | Финальный security baseline audit INFRA-002 | DONE |
| INFRA-002-AUDIT-ORDER-EXEC | Audit order_executor permissions | TODO |
| INFRA-003 | Backup Policy: automated encrypted DB backups to Backblaze B2 | DONE |
| SEC-501-HOST-HARDENING | SSH hardening | TODO |
| postgres-logging-hardening | Enable log_connections/disconnections | TODO |
| firewall-startup-race-fix | Устранить окно незащищённости между docker start и firewall unit | TODO |
| user-provisioning-runbook | Runbook для добавления нового DB user | TODO | |

---

## SYSTEM TASKS

| ID | Задача | Статус |
|----|--------|--------|
| SYS-309 | Daily Data Audit Snapshot (run_data_check.py) | DONE |
| SYS-322 | PRE-PROD-SECRETS-ROTATION: Ротация секретов перед переключением paper → live | DONE |
| SYS-501 | Project Filesystem Cleanup (logs, temp, md artifacts) | DONE |
| SYS-330 | trade_duplicate rate flood investigation | BACKLOG |

---

*Обновлено: 2026-04-11*
