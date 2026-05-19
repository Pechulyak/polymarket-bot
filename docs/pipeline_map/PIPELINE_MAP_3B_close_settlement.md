# ШАГ 3B. ЗАКРЫТИЕ OPEN-ROUNDTRIP ЧЕРЕЗ РЕЗОЛЮЦИЮ РЫНКА (SETTLEMENT)

## Краткая характеристика (TL;DR)

Шаг 3 магистрали разделён на три параллельные ветви по типу действия над `whale_trade_roundtrips`:

- **Шаг 3A** — создание новых OPEN-позиций из BUY-сделок (описан отдельно).
- **Шаг 3B** — закрытие OPEN-позиций через резолюцию рынка (этот документ).
- **Шаг 3C** — закрытие OPEN-позиций через SELL-события (DORMANT в auto-pipeline, описан отдельно).

### Шаг 3B в бизнес-нотации

Каждые 2 часа cron запускает `run_settlement.sh`, который сначала скачивает резолюции рынков с Polymarket CLOB API в таблицу `market_resolutions`, затем JOIN-ит OPEN-позиции в `whale_trade_roundtrips` с резолвнутыми рынками и UPDATE-ит каждую совпавшую позицию до `status='CLOSED'` с финальной ценой 1.0 (победа) или 0.0 (проигрыш) в зависимости от соответствия `outcome` позиции и победителя рынка. Это доминирующий механизм закрытия позиций в текущей production-топологии: SELL-close (шаг 3C) DORMANT.

Шаг описывает только UPDATE OPEN → CLOSED через SQL-функцию `settle_resolved_positions()`. Скачивание резолюций (`fetch_market_resolutions.py`) — upstream-зависимость, sidebar. Пересчёт P&L кита (`update_whale_pnl_from_roundtrips`) — отдельный шаг 4, вызывается из той же cron-задачи через несколько секунд после 3B (см. §14).

---

## 1. Назначение шага

Шаг переводит OPEN-позицию в `whale_trade_roundtrips`, чей рынок завершился с известным победителем, в финальное состояние CLOSED с расчётом P&L. Это **единственный auto-trigger закрытия позиций** в текущей production-топологии: SELL-close (шаг 3C) DORMANT.

Бизнес-смысл: «рынок завершился → знаем победителя → проставляем по каждой открытой позиции, выиграл кит или проиграл, и сколько».

---

## 2. Статус

**CONFIRMED-ACTIVE.** Cron `0 */2 * * *` (`crontab.before:4`) запускает `run_settlement.sh`. Шаг 2 скрипта (`run_settlement.sh:31-32`) вызывает `SELECT * FROM settle_resolved_positions()` через `docker exec polymarket_postgres psql`. Актуальная версия функции включает патч BUG-801 (добавлены `gross_pnl_usd` и `pnl_status` в UPDATE).

Дата верификации: 2026-05-14.

---

## 3. Исходные файлы

**Триггер и оркестрация:**
- `/root/polymarket-bot/scripts/run_settlement.sh` (project files) — bash-скрипт с тремя шагами

**SQL-функция (актуальная версия в production):**
- `scripts/fix_bug801_settle_function.sql` — `CREATE OR REPLACE FUNCTION settle_resolved_positions()` с патчем BUG-801 (добавлен `gross_pnl_usd` и `pnl_status` в UPDATE)
- `scripts/migration_phase3_004_settle_resolved_positions.sql` — оригинальная версия до патча (для контекста)

**DDL читаемой таблицы (источник данных):**
- `scripts/migration_market_resolutions.sql:7-15` — DDL `market_resolutions` (с пробелом RF1)
- `backups/polymarket_20260409_144931.sql:599-600` — production-схема `market_resolutions` с `winner_index SMALLINT`

**DDL целевой таблицы:**
- `scripts/migration_whale_trade_roundtrips.sql` — DDL `whale_trade_roundtrips` (описано в шаге 3A)

---

## 4. Контейнер

Шаг не имеет собственного docker-контейнера. Cron-задача запускает bash-скрипт на хосте, который подключается к существующему контейнеру `polymarket_postgres` через `docker exec` для выполнения SQL. Ранее существовавший docker-сервис `paper_settlement` закомментирован per `SYS-601-FIX` (`docker-compose.yml:152–163`); его функциональность заменена этим bash-скриптом.

Workdir скрипта: `/root/polymarket-bot` (`run_settlement.sh:20`). Точка соединения с БД — контейнер `polymarket_postgres` (имя hardcoded в `run_settlement.sh:31, :38`).

Долгоживущего процесса нет: каждые 2 часа создаётся новый shell-процесс, который завершается после выполнения трёх SQL/Python-вызовов.

---

## 5. Триггер запуска и расписание

| Параметр | Значение | Источник |
|----------|----------|----------|
| Тип триггера | cron | `crontab.before:4` |
| Cron expression | `0 */2 * * *` | `crontab.before:4` |
| Период | 2 часа (каждый чётный час UTC, минута 0) | вычислено |
| Команда | `/root/polymarket-bot/scripts/run_settlement.sh >> /root/polymarket-bot/logs/settlement_cron.log 2>&1` | `crontab.before:4` |
| Альтернативные механизмы | systemd: не найден; docker-compose: закомментирован (`docker-compose.yml:152-163`) | TASK PACK TRIGGER-AUDIT |

Расписание не координируется с docker-контейнером `roundtrip_builder` (шаг 3A, `sleep 7200`): два независимых процесса с одинаковым периодом 2 часа, без синхронизации старта (см. RF2 — race-условие).

---

## 6. Алгоритм шага

### 6.1 Bash-оркестратор `run_settlement.sh`

Последовательность по `run_settlement.sh`:

1. **Загрузка окружения** (`:6-11`):
   - `set -e` — падение любой команды останавливает скрипт
   - `source /root/polymarket-bot/.env` через `set -a / set +a` — все переменные `.env` экспортируются в окружение

2. **Step 1 — Fetch market resolutions** (`:18-27`) — **upstream-зависимость, не часть state-изменения 3B**:
   - `python3 scripts/fetch_market_resolutions.py` — скачивает резолюции из Polymarket CLOB API в `market_resolutions`
   - Явная проверка `$?`: при ненулевом exit → `exit 1` (весь скрипт прерывается)

3. **Step 2 — SQL settlement** (`:29-34`) — **core шага 3B**:
   - `docker exec polymarket_postgres psql -U postgres -d polymarket -t -A -c "SELECT * FROM settle_resolved_positions();"`
   - Результат захватывается в `$SETTLE_RESULT` и логируется через `echo`
   - Возврат функции (набор строк per closed roundtrip) не используется для условной логики

4. **Step 3 — Whale P&L update** (`:36-41`) — **шаг 4, не 3B**:
   - `SELECT updated_count FROM update_whale_pnl_from_roundtrips()`
   - См. §14 — общий триггер с 3B

5. **Завершение** (`:43`): `echo` с `$TIMESTAMP — DONE`.

### 6.2 SQL-функция `settle_resolved_positions()` — главное действие шага

Актуальная версия — `scripts/fix_bug801_settle_function.sql` (replace оригинала после патча BUG-801).

**Сигнатура.** Функция возвращает `TABLE` из 11 колонок: `roundtrip_id`, `market_id`, `wallet_address`, `outcome`, `open_price`, `open_size_usd`, `close_type`, `close_price`, `net_pnl`, `winner_outcome`, `winner_index`. Используется для логирования и аудита, не для последующих SQL-операций.

**Тело — четыре логических блока:**

1. **SELECT-цикл** (`FOR r IN ... LOOP`):
   - JOIN `whale_trade_roundtrips rt` × `market_resolutions mr ON rt.market_id = mr.market_id`
   - WHERE: `rt.status = 'OPEN' AND mr.is_closed = TRUE AND mr.winner_outcome IS NOT NULL AND mr.winner_index IS NOT NULL`
   - Без учёта `outcome` в JOIN — все позиции одного рынка обрабатываются вместе (RF11)

2. **Определение победителя — двойная логика:**
   - **Standard outcomes** по индексу: `LOWER(rt.outcome)` мапится на 0/1 через `CASE` (`'yes'/'up'/'over' → 0`, `'no'/'down'/'under' → 1`, всё остальное → NULL). Сравнивается с `r.winner_index`.
   - **Custom outcomes** по строке: `UPPER(r.outcome) = UPPER(r.winner_outcome)` — для team-markets, где `outcome` — название команды.
   - `v_is_win` = ИСТИНА если ХОТЯ БЫ один из двух механизмов сработал (OR между ними).

3. **Расчёт close_price, close_type, net_pnl:**
   - `v_is_win = TRUE` → `close_price = 1.0`, `close_type = 'SETTLEMENT_WIN'`
   - `v_is_win = FALSE` → `close_price = 0.0`, `close_type = 'SETTLEMENT_LOSS'`
   - `v_net_pnl = (close_price - open_price) * open_size_usd`

4. **UPDATE roundtrip-а:**
   - Цель: одна строка по `WHERE id = r.roundtrip_id` (без повторной проверки status — см. RF10)
   - Поля: `status = 'CLOSED'`, `close_price`, `close_type`, `gross_pnl_usd = net_pnl`, `net_pnl_usd = net_pnl`, `pnl_status = 'CONFIRMED'`, `closed_at = NOW()`

### 6.3 Что не выполняется на шаге 3B

- INSERT новых roundtrip-ов (это 3A).
- UPDATE полей `close_trade_id`, `close_side`, `close_size_usd` — они остаются NULL после settlement (поля для close через SELL, шаг 3C).
- UPDATE `matching_method`, `matching_confidence` — остаются NULL (заполняются только при close через SELL).
- UPDATE `fees_usd` — не модифицируется (см. RF9).
- Пересчёт `whales.total_pnl_usd` — это шаг 4.

---

## 7. Формат входных данных

Чтение из двух таблиц:

**`whale_trade_roundtrips`** — все строки со `status = 'OPEN'`. Используются колонки: `id`, `market_id`, `wallet_address`, `outcome`, `open_price`, `open_size_usd`.

**`market_resolutions`** — строки с `is_closed = TRUE AND winner_outcome IS NOT NULL AND winner_index IS NOT NULL`. Используются колонки: `market_id` (JOIN-ключ), `winner_outcome`, `winner_index`.

DDL `market_resolutions` (production-схема из `backups/polymarket_20260409_144931.sql:599-600`):

- `market_id VARCHAR(255)` PRIMARY KEY
- `is_closed BOOLEAN NOT NULL DEFAULT FALSE`
- `winner_outcome VARCHAR(100)` — название победившего исхода (`'Yes'`, `'Hawks'`, etc.)
- `winner_index SMALLINT` — индекс победившего исхода (0/1 для бинарных)
- `tokens JSONB` — raw данные CLOB API (не используется на 3B)
- `resolution_source VARCHAR(20) NOT NULL DEFAULT 'CLOB'`
- `fetched_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()`
- `resolved_at TIMESTAMP WITH TIME ZONE`

INDEX: `idx_market_resolutions_closed` — partial BTREE на `is_closed WHERE is_closed = TRUE` (`migration_market_resolutions.sql:17-18`). Полезен для фильтра функции.

---

## 8. Формат выходных данных

UPDATE существующих строк в `whale_trade_roundtrips`. Перечень изменяемых полей — в §9. Возврат функции (`RETURN QUERY` per итерация) — набор строк для логирования в bash, наружу не экспортируется.

---

## 9. Записи в БД

### 9.1 Целевая таблица

`whale_trade_roundtrips`. DDL описан в шаге 3A. Constraint `UNIQUE(position_key)` для шага 3B не критичен (UPDATE по PK `id`, не по `position_key`).

### 9.2 Операция шага: UPDATE (не INSERT)

Шаг 3B **только модифицирует** существующие OPEN-roundtrip-ы. Создание новых roundtrip-ов — шаг 3A. Никаких INSERT в `whale_trade_roundtrips` на 3B не выполняется.

### 9.3 Колонки, изменяемые шагом 3B (UPDATE)

| # | Колонка | Бизнес-смысл (5–6 слов) | Источник значения |
|---|---------|--------------------------|-------------------|
| 1 | `status` | финальное состояние позиции в системе | literal `'CLOSED'` |
| 2 | `close_price` | финальная цена позиции при резолюции | `1.0` если WIN, `0.0` если LOSS |
| 3 | `close_type` | тип закрытия позиции через резолюцию | `'SETTLEMENT_WIN'` или `'SETTLEMENT_LOSS'` |
| 4 | `gross_pnl_usd` | валовая прибыль позиции в USD | `(close_price - open_price) * open_size_usd` |
| 5 | `net_pnl_usd` | чистая прибыль позиции после комиссий | = `gross_pnl_usd` (RF9 — `fees_usd` не учитывается) |
| 6 | `pnl_status` | статус достоверности расчёта P&L | literal `'CONFIRMED'` |
| 7 | `closed_at` | время закрытия позиции в системе | `NOW()` в SQL |
| 8 | `updated_at` | служебный timestamp последнего обновления | `NOW()` (через DEFAULT или trigger, явно не выставляется в SQL функции) |

### 9.4 Что НЕ изменяется

Поля, явно остающиеся в исходном состоянии после UPDATE 3B:
- `close_trade_id`, `close_side`, `close_size_usd` — остаются NULL (это поля для SELL-close, шаг 3C)
- `fees_usd` — не модифицируется, остаётся в значении на момент 3A (`0` по умолчанию)
- `matching_method`, `matching_confidence` — остаются NULL (заполняются только при close через SELL)
- `whale_id`, `wallet_address`, `position_key`, `market_id`, `outcome`, `market_title`, `market_category` — read-only для 3B (контракт 3A)
- `open_*` поля — read-only
- `paper_trade_id` — не модифицируется на 3B

### 9.5 Сценарий UPDATE при существующем CLOSED-roundtrip

Функция фильтрует на `WHERE rt.status = 'OPEN'` в SELECT-цикле, поэтому уже CLOSED-roundtrip в LOOP не попадает. Однако между SELECT и UPDATE возможна гонка (см. RF10): UPDATE использует `WHERE id = r.roundtrip_id` без повторной проверки status. В текущей топологии практически безопасно, так как единственный механизм перевода в CLOSED — сам шаг 3B (3C DORMANT).

---

## 10. Условия успеха / частичного успеха / неуспеха

| Исход | Условие | Поведение |
|-------|---------|-----------|
| Полный успех Step 2 | Все JOIN-ed строки UPDATE прошли | `SETTLE_RESULT` логирует список закрытых roundtrip-ов; bash идёт в Step 3 |
| Нет резолвнутых OPEN-позиций | JOIN пустой (нет совпадений `rt.status='OPEN'` × `mr.is_closed=TRUE`) | Функция возвращает 0 строк; нет UPDATE; `SETTLE_RESULT` пустой |
| Step 1 fail (fetch_market_resolutions) | `python3` exit code ≠ 0 | Явный `exit 1` в `run_settlement.sh:24-27`; Step 2 и 3 не запускаются |
| Step 2 fail (psql error) | `docker exec psql` exit code ≠ 0 | `set -e` останавливает скрипт; Step 3 не запускается |
| Частичный fail внутри функции | exception на одной из итераций LOOP | Транзакция функции откатывается полностью (PL/pgSQL); UPDATE-ы предыдущих итераций тоже откатятся |
| `winner_index IS NULL` на резолвнутом рынке | mr.is_closed=TRUE, но winner_index не заполнен | Строка не попадает в SELECT (фильтр функции); OPEN-roundtrip остаётся незакрытым бесконечно (RF8) |

---

## 11. Зависимости

### Upstream

- **Шаг 3A** — `whale_trade_roundtrips` должна содержать OPEN-roundtrip-ы. Без них функция возвращает 0 строк.
- **`fetch_market_resolutions.py`** (Step 1 `run_settlement.sh`) — заполняет `market_resolutions` из Polymarket CLOB API. **Sidebar-зависимость, не часть state-изменения 3B по скоупу α.** Без свежих данных в `market_resolutions` функция работает по последним известным резолюциям.
- **Polymarket CLOB API** — внешний источник резолюций. Доступность API влияет на Step 1, не на Step 2.

### Downstream

- **Шаг 4** (`update_whale_pnl_from_roundtrips`) — агрегирует CLOSED-roundtrip-ы в `whales` (P&L, win_count, loss_count, win_rate). **Запускается из той же cron-задачи** через 4 секунды (`run_settlement.sh:38-39`).
- **Materialized views** (`whale_pnl_summary`, `paper_portfolio_state`, `paper_simulation_pnl` по PROJECT_STATE) — читают `whale_trade_roundtrips`, обновляются по своему расписанию (каждые 2ч по `TEMPLATE_ANALYTICS_CHAT.md`).

### External

- Polymarket CLOB API — только через `fetch_market_resolutions.py`, не вызывается из шага 3B напрямую.
- PostgreSQL на `polymarket_postgres:5432` через `docker exec psql`.

---

## 12. Наблюдаемость

### Логи

Все логи `run_settlement.sh` идут через `echo` с префиксом `[run_settlement]` в stdout. Cron перенаправляет stdout+stderr в `/root/polymarket-bot/logs/settlement_cron.log` через `>> ... 2>&1` (`crontab.before:4`).

Ключевые сообщения за итерацию:
- `[run_settlement] <timestamp> — START`
- `[run_settlement] Step 1: Fetching market resolutions...`
- `[run_settlement] Step 2: Running SQL settlement...`
- `[run_settlement] Settlement result: <output>` — сырой вывод SQL функции
- `[run_settlement] Step 3: Updating whale P&L...`
- `[run_settlement] Whales updated: <count>`
- `[run_settlement] <timestamp> — DONE`

При ошибке Step 1: `[run_settlement] ERROR: fetch_market_resolutions.py failed with exit code <N>`.

### Метрики

Не экспортируются. Состояние шага восстанавливается из логов или SQL-запросом к `whale_trade_roundtrips WHERE close_type IN ('SETTLEMENT_WIN', 'SETTLEMENT_LOSS')`.

### Heartbeat

Отдельного heartbeat-механизма нет. Косвенный признак работы — наличие новых строк в `settlement_cron.log` с timestamp последнего запуска. Healthcheck со стороны Docker (как у 3A) не применяется, так как процесс хостовый, не контейнерный.

### Что наблюдатель НЕ видит

- Сколько именно роundtrip-ов было закрыто за итерацию (только из лога `Settlement result`, парсинг строк).
- Какие OPEN-позиции **должны** были закрыться, но не закрылись из-за NULL `winner_index` / `winner_outcome` (RF8) — нет отдельного логирования.
- Деградацию производительности `settle_resolved_positions()` при росте корпуса.

---

## 13. Особые случаи и риски (RED FLAGs)

**RF1 [P0 для деплоя] — `winner_index` отсутствует в актуальной миграции `market_resolutions`.**
В production-схеме (`backups/polymarket_20260409_144931.sql:599-600`) колонка `winner_index SMALLINT` существует. В `scripts/migration_market_resolutions.sql:7-15` — **отсутствует**. `settle_resolved_positions()` использует её в `WHERE mr.winner_index IS NOT NULL` и в логике определения победителя. Любой fresh deploy, прогоняющий только `migration_market_resolutions.sql`, создаст таблицу без `winner_index` → `settle_resolved_positions()` упадёт с `column does not exist` при первом же запуске. ALTER TABLE для добавления колонки в репозитории не найден — колонка попала в production через ручной `ALTER TABLE` или полный schema restore из дампа. **Приоритет: критический для процедуры деплоя**; в running production не материализуется (колонка уже есть).

**RF2 [P1 — материализован] — Race между BUY-build (3A) и settlement (3B).**
Оба процесса работают с одинаковым периодом 2 часа без синхронизации старта. Контейнер `roundtrip_builder` (sleep 7200) и cron `run_settlement.sh` (`0 */2 * * *`) запускаются независимо. Сценарий: кит купил позицию → BUY-build создал OPEN → кит продал → SELL ушёл в `whale_trades`, но `_close_roundtrips()` DORMANT не сработал → рынок резолвится → settlement закрывает OPEN как SETTLEMENT по бинарному price 0/1, реальная цена выхода кита через SELL потеряна. Доля затронутых позиций (часть с реальными SELL, закрытых settlement-ом раньше) — non-trivial по результатам BUG-608. ARCH-003 в сводке BUG-608.

**RF3 — Неявная проверка exit code SQL-вызовов в bash.**
`run_settlement.sh:31-32, :38-39` оборачивают psql в `$(...)` command substitution. Это захватывает stdout, exit code устанавливается в `$?` после завершения `$(...)`. `set -e` (`:6`) среагирует на ненулевой exit, но **явная проверка `$?` после Step 2 и Step 3 отсутствует** (в отличие от Step 1 на `:22-27`). Поведение корректное, но менее очевидное; при изменении логики легко сломать.

**RF4 — Cron expression не подтверждён live.**
Источник `0 */2 * * *` — `backups/BUG-608-20260505-192231/crontab.before:4` (backup от 2026-05-05). Live `crontab -l` в ask mode не выполнен. После BUG-608 fix крон мог измениться. Open Q1 из отчёта TRIGGER-AUDIT.

**RF5 — Executable bit `run_settlement.sh` не подтверждён.**
`ls -l` в ask mode не выполнен. Если файл потерял `chmod +x` (например при копировании из/в backup), cron-задача упала бы с permission denied, но это не проверено. Open Q2 из отчёта TRIGGER-AUDIT.

**RF6 [P1 — материализован, часть RF2] — Бинарное close_price затирает реальную цену выхода.**
После UPDATE `close_price = 1.0` или `0.0` — независимо от того, по какой цене кит реально вышел. Это корректно для позиций, дошедших до резолюции; **некорректно для позиций, закрытых китом через SELL раньше резолюции**, если SELL-close не успел сработать. Часть ARCH-003.

**RF7 — Покрытие edge-case резолюций.**
Двойная логика winner покрывает: бинарные (Yes/No, Up/Down, Over/Under) через `winner_index` + team-markets через UPPER-string-match. **Не покрыто явно:**
- Tie/draw в спорте (несколько winners или явный tie)
- Cancelled markets (резолюция = NULL/refund)
- Refund situations (Polymarket возвращает позицию по open_price)

Полякетов `is_closed=TRUE AND winner_outcome IS NULL` — отсеивается фильтром RF8, остаётся OPEN бесконечно. Поведение `fetch_market_resolutions.py` на refund/tie — за пределами скоупа 3B.

**RF8 — NULL в `winner_outcome` или `winner_index` блокирует закрытие.**
Фильтр `mr.winner_outcome IS NOT NULL AND mr.winner_index IS NOT NULL` (обе колонки nullable по DDL). Резолвнутый рынок (`is_closed=TRUE`) без одного из этих полей → позиция остаётся OPEN навсегда. Источник заполнения — `fetch_market_resolutions.py` парсинг CLOB API; гарантий заполнения обеих колонок нет (`scripts/fetch_market_resolutions.py:92-110` — `winner_index = None` как default). Латентный source данных в OPEN-state без фактической причины.

**RF9 — `fees_usd` игнорируется в `net_pnl`.**
Формула `v_net_pnl = (v_close_price - r.open_price) * r.open_size_usd`. Поле `fees_usd` (дефолт `0` после 3A) в расчёт не входит. UPDATE проставляет `net_pnl_usd = gross_pnl_usd` — два поля всегда равны. Для paper-аналитики, где комиссии = 0, это нормально; при будущем переходе на real execution с реальными fees `net_pnl_usd` будет некорректным.

**RF10 — UPDATE без проверки status в WHERE.**
SELECT-цикл фильтрует `rt.status = 'OPEN'`, но UPDATE использует `WHERE id = r.roundtrip_id` без повторной проверки status. В текущей топологии (SELL-close DORMANT) единственный источник перевода OPEN→CLOSED — сама эта функция. При ре-активации шага 3C race-условие может привести к UPDATE уже CLOSED-roundtrip-а.

**RF11 — JOIN без учёта `outcome`.**
`JOIN market_resolutions mr ON rt.market_id = mr.market_id` — один резолюшен на рынке закрывает все OPEN-roundtrip-ы кита на этом рынке независимо от `outcome`. Это корректно: каждый roundtrip имеет свой `outcome`, и логика winner определяет WIN/LOSS per позиция. Для китов с мульти-outcome позициями (наблюдение из 3A: `{Yes, No, Cavaliers, Hawks}` на одном market_id) — все 4 позиции закроются в одной итерации, у одной WIN, у трёх LOSS (только один outcome совпадает с winner).

**RF12 — Логи settlement_cron.log без ротации.**
`>> /root/polymarket-bot/logs/settlement_cron.log 2>&1` (`crontab.before:4`) — append без ограничения размера. Logrotate-конфигурация в скоупе не подтверждена. На длинной дистанции файл растёт безгранично.

---

## 14. Результат шага

После успешного выполнения одной итерации `settle_resolved_positions()`:

- Все OPEN-roundtrip-ы, чей `market_id` присутствует в `market_resolutions` с `is_closed=TRUE` и заполненными `winner_outcome`/`winner_index`, переведены в `status='CLOSED'`.
- Каждый закрытый roundtrip имеет проставленные `close_price` (1.0/0.0), `close_type` (`SETTLEMENT_WIN`/`SETTLEMENT_LOSS`), `gross_pnl_usd` = `net_pnl_usd` = `(close_price - open_price) * open_size_usd`, `pnl_status='CONFIRMED'`, `closed_at = NOW()`.
- Поля close-через-SELL (`close_trade_id`, `close_side`, `close_size_usd`, `matching_method`, `matching_confidence`) остаются NULL.
- Сырой `whale_trades` не модифицируется (3B — read-only по отношению к `whale_trades`).
- Резолвнутые рынки с NULL `winner_index` или `winner_outcome` — позиции по ним остаются OPEN (RF8).

**Состояние позиции в магистрали:** позиция кита, чей рынок завершился, переходит в финальное состояние с известным P&L. Дальнейшая жизнь позиции в системе — read-only материал для downstream-агрегации.

### Связь со следующим шагом магистрали

**Шаг 4 — `update_whale_pnl_from_roundtrips`** запускается **внутри той же cron-задачи** `run_settlement.sh`, на строках `:38-39`, через несколько секунд после возврата `settle_resolved_positions()`. Это означает:

- **Триггер шага 4 — общий с 3B**: один cron `0 */2 * * *`, одна bash-задача. Шаг 4 не имеет независимого расписания.
- **Шаги 3B и 4 — последовательные, не параллельные**: 3B завершается полностью до начала 4. Между ними не более 1–2 секунд (стартап psql).
- **Передача данных между шагами — через БД**: 3B пишет в `whale_trade_roundtrips`, 4 читает оттуда же. Никакого argument-passing.
- **Атомарность**: 3B и 4 — две **отдельные транзакции** на стороне БД (два отдельных `docker exec psql -c`). Если 3B успешно закоммитил, а 4 упал — `whale_trade_roundtrips` обновлены, `whales` агрегаты нет. Это создаёт временное расхождение до следующей итерации.

В скоупе магистрали шаг 4 — отдельный документ, описывает `update_whale_pnl_from_roundtrips()` как state-изменение каталога `whales` (не roundtrip-ов). Документ §5 «Триггер запуска» в шаге 4 должен явно указать: «триггер — общий с шагом 3B (cron `run_settlement.sh`)», без дублирования cron-настройки.

**Параллельная ветка закрытия — шаг 3C (DORMANT в auto-pipeline).** В текущей топологии не выполняется; описывается отдельно как dormant route.

---

## 15. Краткая бизнес-формула шага

```
ВХОД: cron 0 */2 * * * → /root/polymarket-bot/scripts/run_settlement.sh
  │   логи в /root/polymarket-bot/logs/settlement_cron.log
  │   .env загружается через source (set -a)
  │
  ├── Step 1 [НЕ шаг 3B, sidebar] python3 scripts/fetch_market_resolutions.py
  │     CLOB API → INSERT/UPDATE в market_resolutions
  │     При exit != 0 — exit 1 (Step 2 и 3 не запускаются)
  │
  ├── Step 2 [ШАГ 3B — state-изменение позиции] docker exec psql:
  │     SELECT * FROM settle_resolved_positions();
  │     │
  │     ├── FOR r IN (SELECT FROM whale_trade_roundtrips rt
  │     │             JOIN market_resolutions mr
  │     │                  ON rt.market_id = mr.market_id
  │     │             WHERE rt.status = 'OPEN'
  │     │               AND mr.is_closed = TRUE
  │     │               AND mr.winner_outcome IS NOT NULL  ← RF8
  │     │               AND mr.winner_index IS NOT NULL)   ← RF8
  │     │
  │     ├── Двойная логика winner:
  │     │     standard outcomes (Yes/No/Up/Down/Over/Under) → 0/1 = winner_index
  │     │     OR  custom outcomes: UPPER(rt.outcome) = UPPER(winner_outcome)
  │     │
  │     ├── WIN → close_price=1.0, close_type='SETTLEMENT_WIN'
  │     │   LOSS → close_price=0.0, close_type='SETTLEMENT_LOSS'  ← RF6
  │     │   net_pnl = (close_price - open_price) * open_size_usd  ← RF9
  │     │
  │     └── UPDATE whale_trade_roundtrips
  │           SET status='CLOSED', close_price, close_type,
  │               gross_pnl_usd=net_pnl, net_pnl_usd=net_pnl,
  │               pnl_status='CONFIRMED', closed_at=NOW()
  │           WHERE id = r.roundtrip_id                            ← RF10
  │
  │     Результат логируется как SETTLE_RESULT (echo).
  │
  ├── Step 3 [НЕ шаг 3B, это шаг 4] docker exec psql:
  │     SELECT updated_count FROM update_whale_pnl_from_roundtrips();
  │     → агрегация CLOSED в whales.total_pnl_usd / win_count / loss_count / win_rate
  │     → описывается отдельным документом шага 4
  │     → триггер — этот же cron (см. §14)
  │
  └── END (timestamp logged)

Что НЕ обновляется на 3B:
  - close_trade_id, close_side, close_size_usd     (поля для 3C SELL-close)
  - matching_method, matching_confidence            (поля для 3C SELL-close)
  - fees_usd                                        (RF9)
  - whale_id, wallet_address, market_id, outcome    (контракт 3A)
  - open_*                                          (read-only для 3B)
  - paper_trade_id                                  (paper-ветка)
  - whales.total_pnl_usd и связанные                (шаг 4)

Параллельная ветка закрытия:
  Шаг 3C — DIRECT_SELL close через _close_roundtrips() в roundtrip_builder.py
  DORMANT в auto-pipeline (флаг --close не используется ни одним cron/docker)
  По объёму — пренебрежимая доля закрытий vs SETTLEMENT.
```
