# TASK_BOARD

> Единственный source of truth для статусов и списка задач проекта.
> Обновляется STRATEGY. Roo выполняет задачи через TASK PACK.

---

## Статусы задач

| Статус | Описание |
|--------|----------|
| TODO | Задача в очереди, не начата |
| IN_PROGRESS | Задача выполняется |
| READY | Задача готова к выполнению |
| DONE | Задача завершена |
| FROZEN | Задача/эпик приостановлен |
| CANCELLED | Задача отменена |
| BACKLOG | В бэклоге (вне приоритета) |

---

## Текущий приоритет

**ACTIVE:** WHALE Copy Strategy (paper trading)

**FROZEN:** Arbitrage | Smart Money

---

## Правила управления задачами

1. Любые изменения TASK_BOARD выполняются только через Roo.
2. Strategy формирует изменение через ORCHESTRATOR TASK PACK.
3. Ручное редактирование TASK_BOARD.md запрещено.
4. TASK_BOARD.html является производным файлом и не редактируется вручную.
5. TASK_ID привязан к EPIC-префиксу: PIPE-*, TRD-*, DATA-*, ANA-*, SEC-*, INFRA-*, HYG-*, DOC-*, BUG-*.

---

## Workflow

1. STRATEGY передаёт задачу в ORCHESTRATOR TASK PACK
2. Roo выполняет задачу и обновляет статус
3. После завершения — верификация + review STRATEGY
4. Изменения фиксируются через git commit с TASK_ID

---

## LANE: WHALE — Whale Copy Strategy

**Статус:** ACTIVE (paper trading)

Информационный блок. Задачи — в EPIC: TRD.

---

## LANE: ARB — Arbitrage

**Статус:** FROZEN

Информационный блок. Задачи отсутствуют.

---

## LANE: SMART — Smart Money

**Статус:** FROZEN

Информационный блок. Задачи отсутствуют.

---

## EPIC: PIPE — Pipeline Refactoring

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| PIPE-001 | WhaleTradesRepo — единая точка записи whale_trades | | DONE |
| PIPE-002 | Переключение whale_detector.py на repo | | DONE |
| PIPE-003 | Переключение whale_tracker.py на repo | | DONE |
| PIPE-004 | Pipeline Monitor + Telegram алерты | | DONE |
| PIPE-005 | Финальная верификация Фазы 1 (24ч) | | DONE |
| PIPE-006 | Аудит: найти все пути записи в whale_trades | | DONE |
| PIPE-007 | Переключение virtual_bankroll.py на WhaleTradesRepo | | DONE |
| PIPE-008 | Переключение whale_poller.py на WhaleTradesRepo | | DONE |
| PIPE-009 | Deprecation whale_trade_writer.py + очистка мёртвых импортов | | DONE |
| PIPE-010 | Аудит и удаление deprecated whale_trade_writer | | DONE |
| PIPE-011 | Аудит: найти все пути записи в paper_trades | | DONE |
| PIPE-012 | Отключение VirtualBankroll paper-trade loop в main.py | | DONE |
| PIPE-013 | Создание PaperTradesRepo (единая точка записи) | | DONE |
| PIPE-014 | Переключение модулей на PaperTradesRepo | | DONE |
| PIPE-015 | Создание DB trigger: whale_trades → paper_trades | | DONE |
| PIPE-016 | Удаление ручного копирования | | DONE |
| PIPE-017 | Аудит текущего settlement в roundtrip_builder | | DONE |
| PIPE-018 | Определить API endpoint для resolution data | | DONE |
| PIPE-019 | Спроектировать market_resolutions таблицу | | DONE |
| PIPE-020 | Перенести settlement логику в БД (trigger/procedure) | | DONE |
| PIPE-021 | Обновить roundtrip_builder.py → использовать БД | | DONE |
| PIPE-022 | Удалить HTTP settlement из roundtrip_builder | | DONE |
| PIPE-023 | Верификация end-to-end | | DONE |
| PIPE-024 | Аудит данных для views (схемы, связи, match rate) | | DONE |
| PIPE-025 | View: whale_pnl_summary | | DONE |
| PIPE-026 | View: paper_portfolio_state | | DONE |
| PIPE-027 | View: paper_simulation_pnl | | DONE |
| PIPE-028 | Cron refresh views + smoke_test checks | | DONE |
| PIPE-029 | Dynamic Kelly — trigger берёт bankroll из view | | DONE |
| PIPE-030 | Финальная верификация Фазы 4 | | DONE |
| PIPE-031 | Аудит текущего Kelly sizing в trigger | | DONE |
| PIPE-032 | strategy_config + estimated_capital schema | | DONE |
| PIPE-033 | Обновление trigger — proportional sizing | | DONE |
| PIPE-034 | Установка estimated_capital для paper кита | | DONE |
| PIPE-035 | Верификация полного pipeline | | DONE |
| PIPE-036 | Roundtrip Builder — создание OPEN roundtrips из BUY событий | | DONE |
| PIPE-037 | Roundtrip Builder — закрытие позиций через SELL события | | DONE |
| PIPE-038 | Roundtrip Builder — settlement через CLOB API | | DONE |
| PIPE-039 | Исправление: whale_trade_roundtrips → whales P&L обновление | | DONE |
| PIPE-040 | Whale Roundtrip Reconstructor | | DONE |
| PIPE-041 | Исправление дублирования roundtrip_builder + broken paper_settlement | | DONE |
| PIPE-042 | Исправление Kelly sizing: минимум $1, максимум 5% bankroll | | DONE |
| PIPE-043 | Аудит фактического состояния задач нового цикла | AUDIT | DONE |

---

## EPIC: TRD — Trading Correctness

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| TRD-401 | Аудит целостности таблицы trades | | BACKLOG |
| TRD-402 | Исправление заполнения полей trades в execution pipeline | | DONE |
| TRD-403 | Верификация settlement behaviour в portfolio view | | TODO |
| TRD-404 | Верификация bankroll в portfolio view | | TODO |
| TRD-405 | Верификация логики Kelly sizing | | DONE |
| TRD-406 | Исправление zero-size paper trades на open path | | DONE |
| TRD-407 | Исследование execution gap (paper_trades vs trades) | | CANCELLED |
| TRD-408 | Исправление traded_at — использовать API timestamp вместо NOW() | | DONE |
| TRD-409 | Исправление интеграции settlement с VirtualBankroll | | DONE |
| TRD-411 | Аудит обработки whale exit и записи buy/sell событий | | DONE |
| TRD-412 | Создание таблицы whale_trade_roundtrips и логики реконструкции позиций | | DONE |
| TRD-413 | Аудит полноты ingestion whale_trades для tracked китов | | DONE |
| TRD-414 | Backup whales and whale_trades + snapshot report | | DONE |
| TRD-415 | Freeze whale discovery and whale_trades writes before cleanup | | DONE |
| TRD-416 | Reduce whales universe to qualified subset and clean whale_trades | | DONE |
| TRD-417 | Audit API response structure across market types before whales schema redesign | | DONE |
| TRD-418 | Transform whales table schema to approved activity-based structure | | DONE |
| TRD-419 | Migrate whales logic from legacy fields to new activity-based fields | | DONE |
| TRD-420 | Рефакторинг whale discovery: initial history aggregation + tiered polling | | DONE |
| TRD-420-A | Per-wallet polling для copy_status='paper' китов | | DONE |
| TRD-420-B | Per-wallet polling для copy_status='tracked' китов (5 мин) | | DONE |
| TRD-421 | Аудит whale_trades — Завершён | | DONE |
| TRD-422 | Добавить market_category в whale_trades и унифицировать запись | | DONE |
| TRD-426 | Исправление tier порогов — 97% HOT | | DONE |
| TRD-427 | Исправление: OPEN roundtrips не обновляются settlement (757 stuck) | | DONE |
| TRD-430 | Аудит paper trading pipeline: trades → settlement → bankroll | | DONE |
| TRD-431 | Исправление потока virtual bankroll через lifecycle трейда | | CANCELLED |
| TRD-432 | Исправление ссылки на days_active (была days_active_7d) | | DONE |
| TRD-433 | Исправление dedup filter paper_trades→trades + bankroll reset | | DONE |
| TRD-434 | Исправление false счётчика new_trades в whale_detector logs | | DONE |
| TRD-435 | Диагностика failure settlement — 0 closed trades с resolved markets | | DONE |
| TRD-436 | Переключение settlement engine с Gamma API на CLOB API | | DONE |
| TRD-437 | Reconciliation bankroll после settlement + исправление event loop | | DONE |
| TRD-438 | Аудит pnl_status UNAVAILABLE в whale_trade_roundtrips | | DONE |
| TRD-439 | Запуск paper-trade pipeline для отобранных китов | | IN_PROGRESS |
| TRD-440 | Исправление застрявших roundtrips — 37 OPEN при resolved markets | | DONE |
| TRD-441 | Классификация и исключение китов | | DONE |

---

## EPIC: DATA — Data Integrity

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| DATA-404 | Reset virtual bankroll for fresh paper trading cycle | | DONE |
| DATA-405 | Cleanup test records from database | | DONE |
| DATA-406 | Remove legacy fields is_winner and profit_usd from whale_trades | | DONE |
| DATA-407 | Исправление market_category в whale_trade_roundtrips | | DONE |

---

## EPIC: ANA — Analytics

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| ANA-401 | Расширить таблицу trades категориями рынков | | CANCELLED |
| ANA-402 | Интеграция Polymarket /categories endpoint | | CANCELLED |
| ANA-403 | Анализ поведения китов по категориям | | CANCELLED |
| ANA-404 | Анализ поведения китов по цене входа (≥0.95, ≤0.05) | | TODO |
| ANA-501 | Ежедневный мониторинг Whale Alert (Слой 1) | | DONE |
| ANA-502 | Еженедельный AI анализ — миграция БД (whale_ai_analysis) | | DONE |
| ANA-502-CRON | Еженедельный анализ: test run + cron | | DONE |
| ANA-502-FIX | Исправление recommendations_json + prompt rules | | DONE |
| ANA-502-SCRIPT | Реализация скрипта еженедельного AI анализа | | DONE |
| ANA-502-SQL | SQL-слой: финальные запросы для еженедельного AI-анализа | | DONE |
| ANA-503 | Whale Universe Quality Analysis | | DONE |

---

## EPIC: SEC — Security

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| SEC-401 | Полный Security Audit (порты, env exposure, docker, firewall) | | DONE |
| SEC-402 | Проверка политики No Public Ports | | DONE |
| SEC-403 | Сканирование сервера на открытые сервисы и уязвимости | | DONE |
| SEC-404 | Ограничить Qdrant только localhost | | DONE |
| SEC-501 | SSH Hardening + проверка инцидента 006.1 | | DONE |
| SEC-502 | SSH hardening | | CANCELLED |
| SEC-503 | PRE-PROD-SECRETS-ROTATION: Ротация секретов перед переключением paper → live | | DONE |
| SEC-504 | Политика хранения логов — journalctl + docker + logrotate | | DONE |
| SEC-505 | Исправление rsyslog suspend/resume flood | | DONE |

---

## EPIC: INFRA — Infrastructure

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| INFRA-001 | Аудит конфигурации безопасности PostgreSQL и сети (Сервер 1) | | DONE |
| INFRA-002 | Создание read-only PostgreSQL user для Grafana | | DONE |
| INFRA-003 | Создание PostgreSQL user order_executor для live trading | | DONE |
| INFRA-004 | Baseline перед INFRA-002-004 retry | | DONE |
| INFRA-005 | Аудит pg_hba.conf — создание users и настройка trust | | DONE |
| INFRA-006 | Подготовить новый pg_hba.conf файл (БЕЗ применения) | | DONE |
| INFRA-007 | Применить pg_hba.conf через docker cp + pg_reload_conf | | DONE |
| INFRA-008 | Сгенерировать self-signed SSL сертификат для PostgreSQL | | DONE |
| INFRA-009 | Включить SSL в PostgreSQL через docker-compose | | DONE |
| INFRA-010 | Заменить host → hostssl в pg_hba.conf | | DONE |
| INFRA-011 | Pre-flight audit — найти использования POSTGRES_PASSWORD | | DONE |
| INFRA-012 | Сменить POSTGRES_PASSWORD на сильный | | DONE |
| INFRA-013 | Firewall hardening — закрыть порт 5433 для всех кроме 62.60.233.100 | | DONE |
| INFRA-014 | Firewall persistence — systemd unit для DOCKER-USER правил | | DONE |
| INFRA-015 | Тест полного подключения с Сервера 2 | | DONE |
| INFRA-016 | Финальный security baseline audit INFRA-002 | | DONE |
| INFRA-017 | Audit order_executor permissions | | DONE |
| INFRA-018 | Backup Policy: automated encrypted DB backups to Backblaze B2 | | DONE |
| INFRA-019 | Daily Data Audit Snapshot (run_data_check.py) | | DONE |
| INFRA-020 | trade_duplicate rate flood investigation | | DONE |
| INFRA-021 | Исправление smoke_test.sh — проверки свежести fetch | | DONE |
| INFRA-022 | Enable log_connections/disconnections | | CANCELLED |
| INFRA-023 | Устранить окно незащищённости между docker start и firewall unit | | CANCELLED |
| INFRA-024 | Runbook для добавления нового DB user | | DONE |
| INFRA-TASKBOARD-HTML | Обновить генератор TASK_BOARD.html под новый формат (LANE + EPIC, колонка Тег, фильтр DONE) | | DONE |

---

## EPIC: HYG — System Hygiene

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| HYG-001 | Очистка проекта (логи, temp файлы, неиспользуемые скрипты) | | DONE |
| HYG-002 | Удалить неиспользуемые docker images и dangling volumes | | DONE |
| HYG-003 | Проверить permissions .env и обработку секретов | | DONE |
| HYG-004 | Docker cleanup — images + build cache | | DONE |
| HYG-005 | Очистка системных логов — journalctl + btmp | | DONE |
| HYG-006 | Container logs — truncate + настройка ротации | | DONE |
| HYG-007 | Project cleanup — logs + pycache + backups | | DONE |
| HYG-008 | Инвентаризация файлов — MD / migrations / Python | | DONE |
| HYG-009 | Рефакторинг структуры TASK_BOARD.md — унификация эпиков, префиксов, формата | | DONE |

---

## EPIC: DOC — Documentation & Governance

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| DOC-601 | Аудит PROJECT_STATE.md на соответствие governance | | DONE |
| DOC-602 | Очистка TASK_BOARD и CHANGELOG — унификация формата | | DONE |
| DOC-GOVERNANCE-UPDATE | Обновить governance-документы под новый формат TASK_BOARD (пункты 6-11) | | DONE |
| DOC-603 | Актуализация PROJECT_STATE.md + запрет snapshot-данных | | DONE |
| DOC-WHALE-SPEC | WHALE_STATUS_TRANSITIONS.md governance spec v1.0 | | DONE |

---

## EPIC: BUG — Cross-cutting Bugs

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| BUG-607 | Исправление: re-discovery перезаписывает excluded-статус | | DONE |

---

*Обновлено: 2026-04-19*
