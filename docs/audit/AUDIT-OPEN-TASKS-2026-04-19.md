# Audit Report — AUDIT-OPEN-TASKS-2026-04-19

**Дата:** 2026-04-19  
**Scope:** 16 задач (TRD × 8, ANA × 1, SEC × 1, INFRA × 5, HYG × 2)  
**Методология:** Чтение файлов, запросы к БД (SELECT, \d, \df), grep по кодовой базе, анализ CHANGELOG  

---

## Summary

| Вердикт | Кол-во | ID |
|---------|--------|-----|
| DONE_HIDDEN | 10 | TRD-402, TRD-406, TRD-412, TRD-417, SEC-502, INFRA-017, INFRA-020, INFRA-024, HYG-002, HYG-003 |
| DONE_PARTIAL | 2 | TRD-403, TRD-404 |
| STILL_TODO | 2 | TRD-407, ANA-404 |
| OBSOLETE | 2 | INFRA-022, TRD-431 |
| UNCLEAR | 0 | — |

---

## Детали по задачам

### TRD-402 — Исправление заполнения полей trades в execution pipeline

- **Вердикт:** DONE_HIDDEN
- **Доказательства:**
  - Таблица `trades` содержит 2346 записей
  - `opportunity_id`: 2346/2346 (100%) заполнен
  - `whale_source`: 2346/2346 (100%) заполнен
  - `market_title`: 2344/2346 (99.9%) заполнен
  - Код [`virtual_bankroll.py`](src/strategy/virtual_bankroll.py:342) правильно записывает все поля при `_save_virtual_trade()`
  - CHANGELOG: "TRD-402 | Goals: populate size correctly, populate opportunity_id..."
- **Gap:** Нет
- **Рекомендация:** Перевести в DONE

---

### TRD-403 — Верификация поведения settlement (sell vs event resolution)

- **Вердикт:** DONE_PARTIAL
- **Доказательства:**
  - [`roundtrip_builder.py`](src/strategy/roundtrip_builder.py:658) содержит `settle_roundtrips_via_gamma()` с логикой SETTLEMENT_WIN/SETTLEMENT_LOSS
  - Таблица `whale_trade_roundtrips`: 19,056 CLOSED, 4,501 OPEN
  - `close_type` CHECK constraint включает: 'SELL', 'SETTLEMENT_WIN', 'SETTLEMENT_LOSS', 'FLIP'
  - CHANGELOG: "TRD-436 | Переключение settlement engine с Gamma API на CLOB API — DONE"
- **Gap:** Функция `settle_resolved_positions()` в БД существует (`\df`), но верификация "sell vs event resolution" поведения требует наблюдения за реальными данными settlement. Проверена структура, но не живое поведение.
- **Рекомендация:** Задача частично выполнена. Settlement через CLOB API реализован. Для полной верификации нужен прогон settlement cycle и проверка результатов.

---

### TRD-404 — Верификация учёта bankroll (entry/exit updates)

- **Вердикт:** DONE_PARTIAL
- **Доказательства:**
  - [`virtual_bankroll.py`](src/strategy/virtual_bankroll.py:148) документирует pipeline: trades → paper_trades → bankroll check → trades(status='open') → available/allocated update
  - Методы `_allocate_capital()` (строка 229) и `_release_capital()` (строка 247) реализованы
  - [`reconcile_from_trades()`](src/strategy/virtual_bankroll.py:1076) позволяет синхронизировать bankroll с таблицей trades
  - Функция `update_whale_pnl_from_roundtrips()` существует в БД
- **Gap:** Согласно feedback от STRATEGY, "таблица trades и virtual_bankroll не используется в текущем pipeline! банкрол расичтвается во view". Текущий pipeline использует `paper_portfolio_state` view вместо virtual_bankroll.py. Верификация требует подтверждения: правильно ли view рассчитывает bankroll.
- **Рекомендация:** Требуется уточнение от STRATEGY: какой pipeline считать "правильным" — старый (virtual_bankroll.py) или новый (view-based)?

---

### TRD-406 — Исправление zero-size paper trades на open path

- **Вердикт:** DONE_HIDDEN
- **Доказательства:**
  - Запрос: `SELECT COUNT(*) FROM paper_trades WHERE size = 0` → **0 записей**
  - Запрос: `SELECT COUNT(*) FROM trades WHERE size = 0` → **0 записей**
  - [`copy_trading_engine.py`](src/execution/copy_trading_engine.py:251) проверяет `copy_size == Decimal("0")` и пропускает такие сделки
  - [`virtual_bankroll.py`](src/strategy/virtual_bankroll.py:554) требует `total_cost < available`, что также блокирует zero-size
- **Gap:** Нет
- **Рекомендация:** Перевести в DONE

---

### TRD-407 — Исследование execution gap (paper_trades vs trades)

- **Вердикт:** STILL_TODO
- **Доказательства:**
  - CHANGELOG: "TRD-407" не упоминается ни в одном commit
  - [`copy_trading_engine.py`](src/execution/copy_trading_engine.py:359) содержит deduplication check, но это не исследование gap
  - STRATEGY feedback: pipeline использует whale_trade_roundtrips как primary source, trades table — вспомогательная
- **Gap:** Задача "исследование" не выполнена. Нет документации об обнаруженном gap (если он есть).
- **Рекомендация:** Либо выполнить исследование, либо переформулировать задачу, либо отменить если gap не существует.

---

### TRD-412 — Создание таблицы whale_trade_roundtrips и логики реконструкции позиций

- **Вердикт:** DONE_HIDDEN
- **Доказательства:**
  - [`migration_whale_trade_roundtrips.sql`](scripts/migration_whale_trade_roundtrips.sql) — миграция создана
  - Таблица `whale_trade_roundtrips`: 23,557 записей (19,056 CLOSED, 4,501 OPEN)
  - [`roundtrip_builder.py`](src/strategy/roundtrip_builder.py:941) реализует OPEN/CLOSE/SETTLE логику
  - CHANGELOG: "TRD-412 | Создание whale_trade_roundtrips table и логики реконструкции позиций китов"
- **Gap:** Нет
- **Рекомендация:** Перевести в DONE

---

### TRD-417 — Audit API response structure across market types

- **Вердикт:** DONE_HIDDEN
- **Доказательства:**
  - [`docs/API_MARKET_TYPES_AUDIT.md`](docs/API_MARKET_TYPES_AUDIT.md) — полный audit report
  - Документ: "Status: AUDIT COMPLETE - PENDING STRATEGY REVIEW"
  - Охвачены 4 market types, 2 API endpoints, 30+ полей
  - Дата: 2026-03-20
- **Gap:** Нет
- **Рекомендация:** Перевести в DONE (STATUS в документе говорит "PENDING STRATEGY REVIEW", но аудит выполнен)

---

### TRD-431 — Исправление потока virtual bankroll через lifecycle трейда

- **Вердикт:** OBSOLETE
- **Обоснование:**
  - Согласно STRATEGY feedback: "таблица trades и virtual_bankroll не используется в текущем pipeline! банкрол расичтвается во view"
  - Текущий pipeline: whale_trade_roundtrips → paper_portfolio_state view → bankroll metrics
  - [`virtual_bankroll.py`](src/strategy/virtual_bankroll.py) —legacy code, не используется в активном pipeline
- **Gap:** Задача утратила актуальность
- **Рекомендация:** Перевести в CANCELLED

---

### ANA-404 — Анализ поведения китов по цене входа (≥0.95, ≤0.05)

- **Вердикт:** STILL_TODO
- **Доказательства:**
  - CHANGELOG: "ANA-404" не упоминается ни в одном commit
  - [`docs/API_MARKET_TYPES_AUDIT.md`](docs/API_MARKET_TYPES_AUDIT.md:333) содержит `average_entry_price` в таблице "Fields NOT Currently Supported"
  - Нет SQL-скрипта, materialized view или отчёта для анализа entry price distribution
  - whale_trades.price содержит данные, но анализ "≥0.95, ≤0.05" не реализован
- **Gap:** Отсутствует SQL-запрос или скрипт для анализа. Нет документации.
- **Рекомендация:** Выполнить задачу или переформулировать/отменить

---

### SEC-502 — SSH hardening

- **Вердикт:** DONE_HIDDEN (OBSOLETE как дубликат)
- **Доказательства:**
  - [`docs/security/SSH_HARDENING.md`](docs/security/SSH_HARDENING.md): SSH hardening выполнен (PasswordAuthentication=no, PermitRootLogin=prohibit-password, fail2ban)
  - SEC-501: DONE в TASK_BOARD
  - SEC-502: TODO в TASK_BOARD (дублирующий статус)
- **Gap:** Нет (SEC-501 покрывает ту же работу)
- **Рекомендация:** Перевести SEC-502 в CANCELLED как дубликат SEC-501

---

### INFRA-017 — Audit order_executor permissions

- **Вердикт:** DONE_HIDDEN
- **Доказательства:**
  - [`config/pg_hba.conf`](config/pg_hba.conf:34): order_executor с hostssl и scram-sha-256
  - Запрос `has_table_privilege('order_executor', 'whale_trades', 'SELECT')` → **t** (true)
  - Запрос `has_table_privilege('order_executor', 'trades', 'SELECT')` → **f** (false)
  - Запрос `has_table_privilege('order_executor', 'whale_trade_roundtrips', 'SELECT')` → **f** (false)
  - Запрос `has_table_privilege('order_executor', 'trades', 'INSERT')` → **f** (false)
  - CHANGELOG: "INFRA-002-AUDIT-ORDER-EXEC | order_executor permissions: только SELECT на 5 таблицах, нет write"
- **Gap:** Нет
- **Рекомендация:** Перевести в DONE

---

### INFRA-020 — trade_duplicate rate flood investigation

- **Вердикт:** DONE_HIDDEN
- **Доказательства:**
  - [`whale_trades_repo.py`](src/db/whale_trades_repo.py:142) содержит `trade_duplicate` debug log
  - [`whale_tracker.py`](src/research/whale_tracker.py:865) содержит закомментированный duplicate skip
  - CHANGELOG: "SYS-330 | trade_duplicate rate flood: дедупликация работает корректно, риск только рост лог-файла"
  - Дедупликация реализована в коде
- **Gap:** Нет
- **Рекомендация:** Перевести в DONE

---

### INFRA-022 — Enable log_connections/disconnections

- **Вердикт:** OBSOLETE
- **Обоснование:**
  - CHANGELOG: "postgres-logging-hardening | log_connections=off, log_disconnections=off, minimal observability"
  - [`docs/INFRA-002-SECURITY-BASELINE.md`](docs/INFRA-002-SECURITY-BASELINE.md:122) показывает: "log_connections: off → **on**" как gap
  - Но в CHANGELOG указано что оставили **off** ("minimal observability")
  - Решение принято: НЕ включать логирование
- **Gap:** Нет (сознательно не реализовано)
- **Рекомендация:** Перевести в CANCELLED с пометкой "решение принято: не включать"

---

### INFRA-023 — Устранить окно незащищённости между docker start и firewall unit

- **Вердикт:** OBSOLETE
- **Обоснование:**
  - CHANGELOG: "firewall-startup-race-fix | Startup race window ~seconds, pg_hba reject компенсирует"
  - [`docs/INFRA-002-SECURITY-BASELINE.md`](docs/INFRA-002-SECURITY-BASELINE.md:47): "Known issue: startup race window (~секунд) между docker.service start и docker-firewall-rules.service start. Компенсируется pg_hba reject вторым слоем."
  - Риск признан low и компенсирован
- **Gap:** Нет (принято решение оставить как есть)
- **Рекомендация:** Перевести в CANCELLED с пометкой "риск признан low, компенсирован pg_hba"

---

### INFRA-024 — Runbook для добавления нового DB user

- **Вердикт:** DONE_HIDDEN
- **Доказательства:**
  - CHANGELOG: "user-provisioning-runbook | Процедура добавления user описана в pg_hba.conf комментариях"
  - [`config/pg_hba.conf`](config/pg_hba.conf:1) содержит подробные комментарии о принципах безопасности и процедуре добавления users
- **Gap:** Нет
- **Рекомендация:** Перевести в DONE

---

### HYG-002 — Удалить неиспользуемые docker images и dangling volumes

- **Вердикт:** DONE_HIDDEN
- **Доказательства:**
  - `docker images`: polymarket-bot-*(3), qdrant, amnezia-awg, postgres, redis, hello-world — нет `<none>` images
  - `docker volume ls`: polymarket-bot_*(5), qdrant_data — нет dangling volumes
  - CHANGELOG: "HYG-004 | Docker cleanup — images + build cache — DONE"
- **Gap:** Нет
- **Рекомендация:** Перевести в DONE

---

### HYG-003 — Проверить permissions .env и обработку секретов

- **Вердикт:** DONE_HIDDEN
- **Доказательства:**
  - `.env`: `-rw-------` (600) — корректные permissions
  - `.env.example`: `-rw-r--r--` (644) — публичный шаблон без секретов
  - `.env.production.template`: `-rw-r--r--` (644) — шаблон
  - [`AGENTS.md`](AGENTS.md:489) документирует правила обработки секретов
- **Gap:** Нет
- **Рекомендация:** Перевести в DONE

---

## Итоговые рекомендации STRATEGY

### Перевести в DONE (10 задач):
- TRD-402, TRD-406, TRD-412, TRD-417
- INFRA-017, INFRA-020, INFRA-024
- HYG-002, HYG-003

### Перевести в CANCELLED (4 задачи):
- SEC-502 — дубликат SEC-501
- INFRA-022 — сознательно не реализовано
- INFRA-023 — риск признан low, компенсирован
- TRD-431 — утратила актуальность

### Требуют уточнения/действия (2 задачи):
- **TRD-403**: Settlement реализован, но верификация "sell vs event resolution" поведения incomplete. Нужен прогон settlement cycle.
- **TRD-404**: Bankroll pipeline изменился (теперь view-based). Нужно уточнить, какой pipeline считать эталоном.

### STILL_TODO (2 задачи):
- **TRD-407**: Требуется исследование execution gap
- **ANA-404**: Анализ entry price не реализован

---

## Verification Checklist

- [x] Каждая из 16 задач получила вердикт
- [x] По каждому DONE_HIDDEN / DONE_PARTIAL — есть конкретная ссылка на код/таблицу/коммит
- [x] По каждому UNCLEAR — сформулирован конкретный вопрос к STRATEGY
- [x] Никаких изменений в TASK_BOARD, БД, коде, конфигах
- [x] Никаких git commit/push
- [x] Файл отчёта: `docs/audits/AUDIT-OPEN-TASKS-2026-04-19.md`