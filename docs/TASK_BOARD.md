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
5. TASK_ID привязан к EPIC-префиксу: PIPE-*, TRD-*, DATA-*, ANA-*, SEC-*, INFRA-*, HYG-*, DOC-*, BUG-*, ACT-*.

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
| PIPE-044 | DDL таблицы leaderboard-воронки кандидатов | | DONE |
| PIPE-045 | Скрипт fetch кандидатов + LP/HFT-фильтры | | DONE |
| PIPE-046 | Скрипт roundtrip scoring + settlement кандидатов | | DONE |
| PIPE-047 | Fix outcome mismatch в paper P&L views | | DONE |
| PIPE-048 | Telegram live-алерты paper-сделок | | DONE |
| PIPE-049 | Fetch кандидатов из 9 категорий leaderboard + populate best_category/categories | | DONE |
| PIPE-050 | NULL-guard в score_leaderboard_candidates.py: 11 групп с NULL price → OPEN (PIPE-050) | | DONE |
| PIPE-051 | Пересмотр HFT-фильтра: кандидат-метрика доля сделок в burst-окнах | | DONE |
| PIPE-052 | Дедуп paper_trade_notifications по whale+market+outcome+side+price в notify_paper_trade() (11 дублей-алертов на одну цену подтверждены на живых данных) | | DONE |

---

## EPIC: TRD — Trading Correctness

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| TRD-401 | Аудит целостности таблицы trades | | CANCELLED |
| TRD-402 | Исправление заполнения полей trades в execution pipeline | | DONE |
| TRD-403 | Верификация settlement behaviour в portfolio view | | DONE |
| TRD-404 | Верификация bankroll в portfolio view | | DONE |
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
| TRD-439 | Запуск paper-trade pipeline для отобранных китов | | DONE |
| TRD-440 | Исправление застрявших roundtrips — 37 OPEN при resolved markets | | DONE |
| TRD-441 | Классификация и исключение китов | | DONE |
| TRD-442 | DB-trigger закрытия paper-позиций на SELL | | CANCELLED |
| TRD-443 | Реактивация _close_roundtrips (exact + fuzzy matching) | | DONE |
| TRD-445 | Hardening тестовой инфраструктуры roundtrip_builder | | DONE |
| TRD-444 | Исправление NULL close_* в whale_trade_roundtrips после settlement | | DONE |
| TRD-446 | split миграции 006 на 006a (schema) + 006b (data); стратегия для ~87% OPEN с outcome=NULL; cleanup dead WARNING в rollback 007a | | TODO | Покрывает HYG-NNN-2, HYG-NNN-8, HYG-NNN-11. Blast radius: высокий (DDL на prod). |
| TRD-447 | Исправление rate-limit bug в _fetch_and_group_sell_trades +_close_roundtrips |  | CANCELLED |
| TRD-448 | Учёт комиссии Polymarket в расчёте PnL | | DONE |
| TRD-449 | Ценовой фильтр входа: отсечка whale-сделок с price > max_entry_price (0.97) | | DONE |
| TRD-450 | Расхождение our_WR/whale_WR у 0xbacd00c9 (paper): наша копи-симуляция WR=40.16% vs WR кита 60.99% (post-reset). Гипотеза про слияние рынков с разными датами резолюции в один market_id проверена и не подтвердилась (нет (market_id,outcome) с разными close_type) — причина не установлена, нужен отдельный debug | | BACKLOG |

---

## EPIC: DATA — Data Integrity

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| DATA-404 | Reset virtual bankroll for fresh paper trading cycle | | DONE |
| DATA-405 | Cleanup test records from database | | DONE |
| DATA-406 | Remove legacy fields is_winner and profit_usd from whale_trades | | DONE |
| DATA-407 | Исправление market_category в whale_trade_roundtrips | | DONE |
| DATA-408 | Идемпотентность whale_trades: partial UNIQUE + ON CONFLICT | feature:data-integrity | DONE |
| DATA-409 | Миграция fetch_trader_trades на /activity endpoint | feature:activity-endpoint | DONE |
| DATA-410 | Whitelist для точечного включения /activity endpoint | feature:activity-endpoint | DONE |
| DATA-411 | Глобальное переключение всех китов на /activity | feature:activity-endpoint | DONE |
| DATA-412 | Outcome по token_id вместо outcome_index | feature:whale-detection | DONE |

---

## EPIC: ANA — Analytics

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| ANA-401 | Расширить таблицу trades категориями рынков | | CANCELLED |
| ANA-402 | Интеграция Polymarket /categories endpoint | | CANCELLED |
| ANA-403 | Анализ поведения китов по категориям | | CANCELLED |
| ANA-404 | Анализ поведения китов по цене входа (≥0.95, ≤0.05) | | BACKLOG |
| ANA-501 | Ежедневный мониторинг Whale Alert (Слой 1) | | DONE |
| ANA-502 | Еженедельный AI анализ — миграция БД (whale_ai_analysis) | | DONE |
| ANA-502-CRON | Еженедельный анализ: test run + cron | | DONE |
| ANA-502-FIX | Исправление recommendations_json + prompt rules | | DONE |
| ANA-502-SCRIPT | Реализация скрипта еженедельного AI анализа | | DONE |
| ANA-502-SQL | SQL-слой: финальные запросы для еженедельного AI-анализа | | DONE |
| ANA-503 | Whale Universe Quality Analysis | | DONE |
| ANA-505 | Tracking coverage metric: измерение доли SELL events с предшествующим matching OPEN roundtrip'ом в close_sell pipeline | | TODO | Связано с RED FLAG #1. Покрывает HYG-NNN-27. Blast radius: низкий (новый read-only artifact). |
| ANA-510 | Отбор 3 китов из public leaderboard | ANA | DONE |

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| SEC-401 | Полный Security Audit (порты, env exposure, docker, firewall) | | DONE |
| SEC-402 | Проверка политики No Public Ports | | DONE |
| SEC-403 | Сканирование сервера на открытые сервисы и уязвимости | | DONE |
| SEC-404 | Ограничить Qdrant только localhost | | DONE |
| SEC-501 | SSH Hardening + проверка инцидента 006.1 | | DONE |
| SEC-502 | SSH hardening | | CANCELLED |
| SEC-503 | Комплексная проверка безопасности | | DONE |
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
| INFRA-025 | Pipeline monitor dry-run + alerts: интеграция dry-run режима в pipeline_monitor.py | | TODO | Покрывает HYG-NNN-24, HYG-NNN-25. Blast radius: низкий (scripts/pipeline_monitor.py). |
| INFRA-026 | Cron/build/backup hygiene: обёртка cron, image rebuild, backup verification | | DONE |
| INFRA-027 | Host DB tooling + dedicated writer user: DB-тулинг на хосте + выделенный writer user | | TODO | Покрывает HYG-NNN-18, HYG-NNN-20, HYG-NNN-17. Blast radius: высокий (GRANT/REVOKE prod). |
| INFRA-028 | Партиционирование whale_trades по месяцам | | CANCELLED |
| INFRA-029 | Анализ партиционирования (ON CONFLICT compatibility) | | CANCELLED |
| INFRA-030 | Retention whale_trades (архив + cron) | | DONE | |
| INFRA-031 | Выравнивание индексов whale_trades repo ↔ live | 12.7s→4.0s | DONE |
| INFRA-032 | Фикс деградации _fetch_and_group_sell_trades() — фильтры по времени и copy_status | | DONE |
| INFRA-033 | Заменить p95_24h на last+recent логику в pipeline_monitor | | DONE |
| INFRA-034 | Фикс sell-запроса (remove LOWER, add partial index) | | DONE |
| INFRA-035 | Обновить пороги duration: WARNING=1200s, CRITICAL=1800s + context messages | | DONE |
| INFRA-036 | Фикс backup .env path + emergency alert bus | | DONE |
| INFRA-037 | Tune work_mem + swappiness for close_sell spill | | DONE |
| INFRA-038 | Защита whale_trades от бёрст-загрязнения | | DONE |
| INFRA-039 | Детект остановки записи whale_trades: столбец inserted_at + проба свежести в pipeline_monitor | | DONE |
| INFRA-040 | Heartbeat от paper-polling: detection заморозки (single writer + healthcheck -mmin -3) | | DONE |
| INFRA-041 | Recovery автоперезапуск whale-detector (autoheal) | | FROZEN |
| INFRA-042 | Alert при unhealthy/устаревшем heartbeat (Telegram) | | DONE |
| INFRA-043 | Схема live_orders + grant order_executor | feature:live-execution | DONE |
| INFRA-044 | Backfill CPU saturation S1: cron без flock + прогон > интервал → накопление экземпляров → 100% CPU. Фикс: flock -n + 6ч | | DONE |
| INFRA-045 | Таблица system_state + grant order_executor для cross-server heartbeat | feature:live-execution | DONE |
| INFRA-046 | Heartbeat-alert демона live_executor в pipeline_monitor (edge-trigger, 1 alert на фронт, порог 120с) | feature:live-execution | DONE |
| INFRA-047 | Watchdog застрявших ордеров в pipeline_monitor | feature:live-execution | DONE |
| INFRA-048 | Watchdog live_copy_daemon heartbeat: edge-trigger, порог 180s, alert_state в system_state | feature:live-execution | DONE |
| INFRA-049 | filled_size для maker-пути (taker готов, maker ждёт образца get_order) | feature:live-execution | TODO |
| INFRA-050 | farming-daemon.service отсутствует в репо — добавить в deploy/ (по аналогии с polymarket-copy-live-daemon.service) | feature:systemd | BACKLOG |
| INFRA-051 | Cron protection: эталон crontab в git (docs/crontab.reference) + проверка живости cron в pipeline_monitor (diff crontab -l vs эталон + свежесть маркер-файла) | | DONE |
| INFRA-052 | mm.sh: claude -p подхватывал CLAUDE.md + кастомных субагентов (cwd=repo) → исполнитель изображал оркестратора (TaskCreate себе подзадач, рекурсивный вызов mm.sh на себя, Agent-тул debugger), завис в цикле. Фикс: --safe-mode (без изменения авторизации) + technical deny на самовызов mm.sh/claude/Agent | | DONE |

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
| HYG-010 | Docker cleanup post-TRD-443: образы, build cache, dangling volumes | | DONE |
| HYG-011 | Удаление мёртвого модуля whale_roundtrip_reconstructor.py | | DONE |
| HYG-012 | Улучшение help text --sentinel-method | | DONE |
| HYG-013 | Удаление dead fields из close_data dict | | DONE |
| HYG-014 | Удаление deprecated Python SETTLEMENT path в roundtrip_builder.py | | DONE |
| HYG-015 | Документировать семантику open_trade_id в whale_trade_roundtrips (= last fill of multi-fill order, не first) | | DONE |
| HYG-016 | Удаление whale_trades_legacy | | DONE |

---

## EPIC: DOC — Documentation & Governance

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| DOC-601 | Аудит PROJECT_STATE.md на соответствие governance | | DONE |
| DOC-602 | Очистка TASK_BOARD и CHANGELOG — унификация формата | | DONE |
| DOC-603 | Актуализация PROJECT_STATE.md + запрет snapshot-данных | | DONE |
| DOC-604 | CHAT GOVERNANCE: правило context-first для Roo dispatch | | DONE |
| DOC-605 | Обновить governance-документы под новый формат TASK_BOARD (пункты 6-11) | | DONE |
| DOC-606 | WHALE_STATUS_TRANSITIONS.md governance spec v1.0 | | DONE |
| DOC-607 | Карта магистрали сделки кита (PIPELINE_MAP) | | DONE |
| DOC-608 | PIPELINE_MAP_3C_close_sell.md: переработка от DORMANT к deployed-state | | DONE |

---

## EPIC: BUG — Cross-cutting Bugs

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| BUG-607 | Исправление: re-discovery перезаписывает excluded-статус | | DONE |
| BUG-608 | Закрытие позиций roundtrip_builder не выполняется в проде | | DONE |
| BUG-609 | False CRITICAL in pipeline_monitor (last vs breaching value) | | DONE |
| BUG-610 | Защита пула соединений whale_detector: pool_pre_ping + statement_timeout против заморозки event loop | | DONE |

---

## EPIC: ACT — Account Activity / Portfolio Tracking

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| ACT-001 | Probe /activity + /positions API (schema recon) | | DONE |
| ACT-002 | account_activity + account_positions_snapshot: DDL + fetch + backfill | | DONE |
| ACT-003 | Cron: daily fetch both scripts (env-pattern + flock) | | DONE |
| ACT-004 | Сверка account_activity с CSV + backfill deposit-событий | | DONE |
| ACT-005 | Grafana-дашборды Farming Daily + Position Lifecycle (SQL-слой) | | DONE |
| ACT-006 | account_daily_position_ledger — mark-to-market витрина позиций (замена ACT-005 view) | | DONE |
| ACT-007 | Backfill CLOB /prices-history — дневная mark-цена вне farm/снапшот-окна | | BACKLOG |
| ACT-008 | CLOB /trades maker/taker matching — точные buy_fee/sell_fee | | BACKLOG |
| ACT-009 | account_activity теряет сделки при коллизии дедуп-ключа (одинаковые tx_hash+size+price, разные ордера) | | BACKLOG |

---

## EPIC: FARM — Liquidity Farming

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| FARM-001 | Farming daemon: on-chain inventory, throttle, systemd | feature:liquidity-farming | DONE |
| FARM-002 | Farming live: two-sided maker, smoke+scoring | feature:liquidity-farming | DONE |
| FARM-003 | Инцидент-фиксы: reconcile книга=истина, F2 offset/requote инвариант, ASK-cap inv, skew reseed, last_ts персистентность | feature:liquidity-farming | DONE |
| FARM-004 | Telegram alert-система: 6 TG-алертов, русификация, edge-latch в farming_state.json, st["ids"] gate против осцилляции, #4 balance-reject парсинг, LIVE-флип | feature:liquidity-farming | DONE |
| FARM-005 | Dynamic BID cap (free cash) + inv-overshoot fix: partial-BUY hold, reseed-гейт, авторазгрузка излишка (Decimal tick) | feature:liquidity-farming | DONE |
| FARM-006 | TG onset/recovery, reseed-adoption при рестарте, unload_id-трекинг + ревью-фиксы | feature:liquidity-farming | DONE |
| FARM-007 | Unified inv-cap MAX_INV=450, Fix 1/Fix 2 удалены, inv=None fail-closed | feature:liquidity-farming | DONE |
| FARM-008 | External heartbeat watcher (dead-process detection) | feature:liquidity-farming | TODO |
| FARM-009 | Requote burns epoch score (оптимизация) | feature:liquidity-farming | TODO |
| FARM-010 | Скринер v4 (farm_screen.py): Gamma Phase A, метрика our_daily=our_share×pool, отсечка volatile/thin. Farm маргинален при $231 | feature:liquidity-farming | DONE |
| FARM-011 | Circuit breaker: сдвиг mid ≥2¢/10мин → cancel all + кулдаун 15мин, recovery по стабильности | feature:liquidity-farming | DONE |
| FARM-012 | Fill-реакция: fill/missing-leg → пауза 120с (merge кулдаунов через max), персистентность pause_until | feature:liquidity-farming | DONE |
| FARM-013 | Websocket CLOB WSS (латентность 10-20с → <1с) — заморожен: +$4.86/д на дне катастрофы 03.07, burst-филлы не ловит | feature:liquidity-farming | FROZEN |
| FARM-014 | ROUND_HALF_UP в _round (оба пути ценообразования) | feature:liquidity-farming | DONE |
| FARM-015 | markets.json schema + export script (min_size, inv_center, inv_deadband, max_inv, weight, gamma_id, condition_id); migration_farm024 adds columns; export_farming_markets.py. Pre-gate: schema + migration + export. Post-gate: загрузка markets.json в демон, cash-аллокатор, параллельный поллинг (гейт: ≥$2.5/д после 2 недель live) | feature:liquidity-farming | IN_PROGRESS |
| FARM-016 | save_state_file сохраняет курсоры токенов вне текущего MARKETS (регрессия n=93) | feature:liquidity-farming | DONE |
| FARM-017 | Deadband=нога, max_inv=center+2×нога безусловным капом, long_unload → BID-widening ×2 (поглощает FARM-004j) | feature:liquidity-farming | DONE |
| FARM-018 | Скринер: добор пагинации диапазона 20-50k (Streeting liq=37k теряется за GAMMA_PAGES=5) | feature:liquidity-farming | TODO |
| FARM-019 | Telegram control bot: long-polling getUpdates, whitelist, /status (per-market + last log line), /stop + /confirm_stop, /start + /confirm_start | feature:liquidity-farming | DONE |
| FARM-020 | Graceful shutdown: SIGTERM handler cancel all + save state + exit 0, TimeoutStopSec=120 | feature:liquidity-farming | DONE |
| FARM-020-fix | one_sided latch bug: place_two_sided return → XOR = one_sided; non-requote → reconcile only if full path; skip latch on early-return | feature:liquidity-farming | DONE |
| FARM-021 | hardening: normalize st["ids"] after RESEED adoption to 2-tuple (bid_id, ask_id), None for missing leg — unpack at alert block fragile to future code paths | feature:liquidity-farming | BACKLOG |
| FARM-022 | DONE: (K1) farm_screen→DB candidates+fees, cron 2×/день, retention 30d; (K2) degradation-watch в pipeline_monitor (pool/max_spread/fees/end_date); (K3) TG-дайджест топ-5+дельты, cron after farm_screen | feature:liquidity-farming | DONE |
| FARM-023 | book_depth per-side + thin_book фильтр в скринере и дайджесте | feature:liquidity-farming | DONE |
| FARM-025 | level-gate после адверс-филла: запись last_adverse_fill в fill-ветке, level-gate при resume (mid ±1 tick), halted state с manual reset, halted+last_adverse_fill персистентны в farming_state.json | feature:liquidity-farming | DONE |
| FARM-026 | Ротация портфолио фарминга (NL→Phillies+Requião) + F3-допуск дробного хвоста | feature:liquidity-farming | DONE |
| FARM-027 | Нормализация marginal в calc_farm_economics (%ср, порог 70%) | feature:liquidity-farming | DONE |
| FARM-028 | quote_size отдельным полем конфига, развязать с min_size | feature:liquidity-farming | BACKLOG |
| FARM-029 | Автокалькуляция center/deadband/max_inv от quote_size (center=quote_size, dead=0.5×quote_size, max_inv=2×center+нога) | feature:liquidity-farming | BACKLOG |
| FARM-030 | /status контрол-бота — динамический список рынков + отображение halted | feature:liquidity-farming | DONE |
| FARM-031 | check_fills — фильтровать собственные taker-сделки (3 ложные адверс-паузы 09.07) | feature:liquidity-farming | BACKLOG |
| FARM-033 | Дневной снапшот фарминга: таблица farming_daily_snapshot (migration_farm033.sql) + сборщик farming_snapshot.py. Источники: earnings API (c.get_earnings_for_user_for_day), on-chain inv (ERC-1155 balanceOf), trades fees (taker-only, TRD-448 formula). legs_state/hours_both реконструкция из fills + open orders + halted. UPSERT по (snap_date, token). Деплой на S2 + cron отдельно. | feature:liquidity-farming | DONE |
| FARM-035 | Recover недостающей ноги из HOLD (ASK skipped по locked_sell при requote) | feature:liquidity-farming | BACKLOG |
| FARM-036 | Алерт-латч не сбрасывать на API-ошибке get_open_orders | feature:liquidity-farming | DONE |
| FARM-037 | Деплой US Soft Landing + Raquel Lyra (leg 100, override thin-вето soft landing, параметры 100/100/50/300, capital +$192) | feature:liquidity-farming | DONE |
| FARM-038 | Фикс share-модели calc_farm_economics + farm_screen: comp_pts = min(bid,ask) + abs(bid−ask)/3 (модель Polymarket Qmin) вместо min-модели (calc, завышение 2-5x) и суммы сторон (screen, занижение 2-2.5x). Вычет собственных ордеров в calc (--our-bid/--our-ask). Метка upper-bound; калибровка факт/прогноз ~0.3-0.4. Паритет верифицирован (Alito 1388704, share=0.0304 в обоих). pts_k теперь = comp_pts/1000 — старые сканы несравнимы напрямую. | feature:liquidity-farming | DONE |
| FARM-039 | farm_screen ингест: окна Gamma по liquidity (100/окно) теряют рынки (прецедент 15.07: Farage 2846103, Discord 2698822 выпали из прогона). Нужны полная пагинация + verbose-причина отсева per market. | feature:liquidity-farming | BACKLOG |
| FARM-040 | Отключение дублирующего farm-degradation алертинга на S1 (K2 из FARM-022) | feature:liquidity-farming | DONE |
| FARM-041 | Рестарт-пакет демона фарминга: markets.json из БД вместо хардкода (генератор для S2 + загрузка в демоне/control-боте с fallback) + circuit breaker не отменяет unload-ордер | feature:liquidity-farming | DONE (деплой S2 — отдельная задача) |

## EPIC: LIVE — Live Execution

| ID | Задача | Тег | Статус |
|----|--------|-----|--------|
| LIVE-001 | Доработка live-executor: routing maker/taker, market-order FOK | feature:live-execution | DONE |
| LIVE-002 | systemd auto-start демона live-executor | feature:live-execution | DONE |
| LIVE-003 | Throttle ошибок демона + route column live_orders + filled_size taker | feature:live-execution | DONE |
| LIVE-004 | Live copy: проброс token_id и auto-copy paper→live | feature:live-execution | DONE |
| LIVE-005 | on-chain balance-gate + фикс $1 | feature:live-execution | DONE |
| LIVE-006 | Версионирование executor-кода: папка executor/ в репо) | feature:live-execution | DONE |
| LIVE-007 | live-киты не поллились (fetch WHERE только paper/tracked): добавлен 'live' в paper-ветку fetch | feature:live-execution | DONE |
| LIVE-008 | Дедуп live-ордеров по позиции (аналог PIPE-052) | feature:live-execution | DONE |
| LIVE-009 | submit_taker всегда шлёт side=BUY, игнорируя SELL-intent | feature:live-execution | DONE |
| LIVE-010 | SELL-support для live-пути (сейчас SELL блокируется, LIVE-009) | feature:live-execution | BACKLOG |
| LIVE-011 | 28% (15 из 53) live_orders со status='failed' — расследовать причину отказов исполнения | feature:live-execution | BACKLOG |

---

*Обновлено: 2026-07-14*
