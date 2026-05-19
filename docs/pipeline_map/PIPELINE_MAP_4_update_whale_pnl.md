# ШАГ 4. АГРЕГАЦИЯ ROUNDTRIP-ОВ В P&L КИТА

## Краткая характеристика (TL;DR)

Каждые 2 часа cron-задача `run_settlement.sh` третьим (последним) шагом вызывает SQL-функцию `update_whale_pnl_from_roundtrips()`, которая одним statement-ом сканирует все CLOSED-roundtrip-ы в `whale_trade_roundtrips`, группирует их по `wallet_address` и UPDATE-ит соответствующие строки в `whales`: суммарный P&L, число побед/поражений, win rate, общее число завершённых позиций. Это финальный шаг магистрали одной сделки: с этого момента данные кита достигли конечного состояния в системе и становятся материалом для governance-фазы (см. §14).

Триггер шага 4 — общий с шагом 3B (одна cron-задача, две последовательные транзакции). Объект магистрали меняется: на шагах 3A/3B/3C он был **позицией** в `whale_trade_roundtrips`, теперь — **кит** в `whales`.

---

## 1. Назначение шага

Перевод per-position P&L данных (закрытых roundtrip-ов) в **денормализованные агрегаты на уровне кита**. Без этого шага суммарный P&L кита, win rate и число завершённых позиций существовали бы только как ad hoc `SUM/COUNT` запросы к `whale_trade_roundtrips`. Денормализация в `whales` обеспечивает дешёвое чтение для governance-решений оператора, отчётов и downstream-аналитики.

Бизнес-смысл: «у каждого кита теперь явно записано, сколько он суммарно заработал, сколько раз выигрывал, сколько проигрывал — на основании всех его завершённых позиций».

---

## 2. Статус

**CONFIRMED-ACTIVE.** SQL-функция `update_whale_pnl_from_roundtrips()` вызывается из `run_settlement.sh:38-39` в каждой итерации cron-задачи `0 */2 * * *`. Тело функции — production-версия в `scripts/migration_phase3_005_update_whale_pnl.sql`, верифицировано идентичность с production-backup `backups/polymarket_20260409_144931.sql:383-419`.

Дата верификации: 2026-05-14.

---

## 3. Исходные файлы

**SQL-функция:**
- `scripts/migration_phase3_005_update_whale_pnl.sql:4-39` — определение `update_whale_pnl_from_roundtrips(p_wallet_address VARCHAR DEFAULT NULL)`

**Триггер и оркестрация:**
- `/root/polymarket-bot/scripts/run_settlement.sh:38-39` — вызов через `docker exec polymarket_postgres psql`

**DDL целевой таблицы:**
- `scripts/init_db.sql:194-201` — P&L-колонки `whales`, добавленные миграцией `ARC-501`

**DDL источника данных:**
- `scripts/migration_whale_trade_roundtrips.sql` — DDL `whale_trade_roundtrips` (описана в шаге 3A)

---

## 4. Контейнер

Собственного docker-контейнера нет. SQL-функция исполняется в контейнере `polymarket_postgres` по запросу cron-задачи на хосте через `docker exec`. Долгоживущего процесса не существует: один statement, один psql-вызов, завершение.

Точка соединения с БД — `polymarket_postgres` (имя hardcoded в `run_settlement.sh:38`). Соединение — обычное `psql -U postgres -d polymarket` без дополнительных параметров.

---

## 5. Триггер запуска и расписание

Триггер общий с шагом 3B — один cron, одна bash-задача.

| Параметр | Значение | Источник |
|----------|----------|----------|
| Тип триггера | cron | `crontab.before:4` |
| Cron expression | `0 */2 * * *` | `crontab.before:4` |
| Период | 2 часа | вычислено |
| Положение в bash-скрипте | Step 3 (после Step 1 — fetch_market_resolutions, Step 2 — settle_resolved_positions) | `run_settlement.sh:37-41` |
| Альтернативный механизм запуска | Параметр `p_wallet_address` для per-whale recompute — в production не используется | `migration_phase3_005:4`, `run_settlement.sh:39` |

В production вызов идёт **без аргумента** → `p_wallet_address IS NULL` → UPDATE по всем китам, у которых есть хотя бы один CLOSED-roundtrip.

---

## 6. Алгоритм шага

### 6.1 Bash-обвязка

`run_settlement.sh:37-41`:

```
echo "[run_settlement] Step 3: Updating whale P&L..."
UPDATED=$(docker exec polymarket_postgres psql -U postgres -d polymarket -t -A -c \
    "SELECT updated_count FROM update_whale_pnl_from_roundtrips();")
echo "[run_settlement] Whales updated: $UPDATED"
```

Результат функции (`updated_count`) захватывается в bash-переменную и логируется. Условной логики на основе значения нет.

### 6.2 SQL-функция — один statement

Функция содержит **один UPDATE-statement** (плюс служебный `GET DIAGNOSTICS` и `RETURN QUERY`). Не цикл, не несколько последовательных запросов — все агрегаты считаются за один проход PostgreSQL планировщика.

Структура statement-а — `UPDATE ... FROM subquery`:

1. **Subquery** (`migration_phase3_005:21-32`):
   - `SELECT FROM whale_trade_roundtrips`
   - `WHERE status = 'CLOSED'`
   - `GROUP BY wallet_address`
   - Агрегаты на группу:
     - `COUNT(*)` — общее число CLOSED-позиций кита
     - `COUNT(*) FILTER (WHERE net_pnl_usd > 0)` — число побед
     - `COUNT(*) FILTER (WHERE net_pnl_usd <= 0)` — число проигрышей (включая break-even, см. RF3)
     - `COALESCE(SUM(net_pnl_usd), 0)` — суммарный P&L
     - `COALESCE(AVG(net_pnl_usd), 0)` — средний P&L на позицию

2. **JOIN UPDATE** (`migration_phase3_005:9, :33-34`):
   - `UPDATE whales w SET ... FROM (...subquery...) sub WHERE w.wallet_address = sub.wallet_address`
   - Опциональный фильтр `AND (p_wallet_address IS NULL OR w.wallet_address = p_wallet_address)` — в production NULL, фильтр не активен

3. **SET-клауза** (`:11-20`):
   - `win_count = sub.wins`
   - `loss_count = sub.losses`
   - `total_roundtrips = sub.total`
   - `total_pnl_usd = sub.total_pnl`
   - `avg_pnl_usd = sub.avg_pnl`
   - `win_rate_confirmed = CASE WHEN sub.total > 0 THEN sub.wins::DECIMAL / sub.total ELSE 0 END`
   - `last_pnl_updated = NOW()`

4. **Return** (`:36-37`):
   - `GET DIAGNOSTICS v_updated = ROW_COUNT` — захват числа обновлённых строк UPDATE-а
   - `RETURN QUERY SELECT v_updated` — возврат одной строки с одной колонкой `updated_count`

### 6.3 Свойства алгоритма

- **Full recompute, не incremental.** Каждый вызов полностью пересчитывает агрегаты по всем китам с CLOSED-roundtrip-ами. Дельта с прошлой итерацией не учитывается; даже если ни одна новая позиция не закрылась, все строки `whales` всё равно UPDATE-ются (RF1).
- **Через `wallet_address`, не `whale_id`.** Subquery читает `wallet_address` из roundtrip-а; JOIN с `whales` тоже по `wallet_address`. Это означает: roundtrip с `whale_id IS NULL` (наследие RF#1 шага 2B / RF8 шага 3A) **всё равно агрегируется**, если у него есть `wallet_address` и существует строка в `whales` с таким же `wallet_address`. NULL-handling штатный.
- **Атомарный statement.** Один UPDATE — одна транзакция (неявная). Промежуточного состояния «часть китов обновлены, часть нет» при успешном выполнении не существует.

### 6.4 Что не выполняется на шаге 4

- Чтение `market_resolutions` — не нужно, всё необходимое уже агрегировано в `net_pnl_usd` roundtrip-ов на шаге 3B.
- Создание новых записей в `whales` — только UPDATE существующих. Если у кита есть CLOSED-roundtrip, но нет строки в `whales` (теоретический edge case), JOIN не сработает, агрегат не запишется (RF8).
- INSERT/UPDATE в `whale_trade_roundtrips` — функция к ней read-only.

---

## 7. Формат входных данных

Чтение из одной таблицы — `whale_trade_roundtrips`. Используются колонки: `wallet_address`, `status` (фильтр), `net_pnl_usd` (агрегация).

Фильтры применяются только к `status = 'CLOSED'`. Не фильтруется по:
- `pnl_status` — `'CONFIRMED'` / `'ESTIMATED'` / `'UNAVAILABLE'` все попадают в агрегат (RF4)
- `close_type` — `'SETTLEMENT_WIN'` / `'SETTLEMENT_LOSS'` / `'SELL'` / `'FLIP'` все попадают
- `whale_id` — может быть NULL, аналогично RF8 шага 3A

Опциональный параметр функции `p_wallet_address VARCHAR` (`migration_phase3_005:4`) позволяет per-whale пересчёт; в production не используется.

---

## 8. Формат выходных данных

UPDATE существующих строк `whales`. Перечень изменяемых колонок — в §9. Возврат функции — одна строка с `updated_count INT` (число обновлённых строк), используется только для логирования в bash.

---

## 9. Записи в БД

### 9.1 Целевая таблица

`whales`. DDL P&L-колонок — `init_db.sql:194-201` (миграция `ARC-501`).

### 9.2 Операция шага: UPDATE (не INSERT)

Шаг 4 только модифицирует существующие строки `whales`. Создание новых китов — шаг 2A. Никаких INSERT в `whales` на шаге 4 не выполняется.

### 9.3 Колонки, изменяемые шагом 4

| # | Колонка | Тип / Default | Бизнес-смысл (5–6 слов) | Источник значения |
|---|---------|--------------|--------------------------|-------------------|
| 1 | `win_count` | `INTEGER NOT NULL DEFAULT 0` | число выигранных позиций кита | `COUNT(*) FILTER (WHERE net_pnl_usd > 0)` |
| 2 | `loss_count` | `INTEGER NOT NULL DEFAULT 0` | число проигранных позиций кита | `COUNT(*) FILTER (WHERE net_pnl_usd <= 0)` — break-even включён в loss (RF3) |
| 3 | `total_roundtrips` | `INTEGER NOT NULL DEFAULT 0` | общее число закрытых позиций кита | `COUNT(*)` по CLOSED-roundtrip-ам кита |
| 4 | `total_pnl_usd` | `DECIMAL(20,8) NOT NULL DEFAULT 0` | суммарная прибыль кита в USD | `COALESCE(SUM(net_pnl_usd), 0)` |
| 5 | `avg_pnl_usd` | `DECIMAL(20,8) NOT NULL DEFAULT 0` | средняя прибыль на позицию кита | `COALESCE(AVG(net_pnl_usd), 0)` |
| 6 | `win_rate_confirmed` | `DECIMAL(5,4) NOT NULL DEFAULT 0` | доля прибыльных позиций кита | `wins / total` если total>0, иначе 0 |
| 7 | `last_pnl_updated` | `TIMESTAMP` (nullable) | время последнего пересчёта P&L | `NOW()` в SQL |

### 9.4 Что НЕ изменяется

Все остальные колонки `whales` шагом 4 не модифицируются. В частности:
- `wallet_address`, `whale_id` — JOIN-ключ, read-only
- `copy_status` — governance-поле, меняется только оператором (см. §14)
- `qualification_status`, `tier`, `whale_category` — governance-поля
- `total_trades`, `total_volume_usd`, `avg_trade_size_usd`, `trades_last_3_days/7_days`, `days_active_*` — заполняются шагом 2A и cron-задачей `update_whale_activity_counters` (hourly)
- `estimated_capital`, `capital_estimation_method` — отдельный процесс капиталометрии
- `notes`, `whale_comment`, `exclusion_reason`, `reviewed_at` — операторские поля

### 9.5 Сценарий повторного выполнения

При каждой итерации функция выполняет full recompute независимо от того, появились ли новые CLOSED-roundtrip-ы с прошлого запуска. Если за период между двумя cron-итерациями ни одна позиция не закрылась, агрегаты кита получат идентичные значения (RF1 — избыточная работа), но `last_pnl_updated` всё равно обновится до текущего `NOW()`.

---

## 10. Условия успеха / частичного успеха / неуспеха

| Исход | Условие | Поведение |
|-------|---------|-----------|
| Полный успех | UPDATE прошёл атомарно | `updated_count` = число обновлённых китов; bash логирует, скрипт завершает успешно |
| Нет данных для агрегации | Subquery вернула 0 строк (нет CLOSED-roundtrip-ов в системе) | UPDATE 0 строк, `updated_count = 0`, скрипт завершает успешно |
| Кит есть в roundtrip, но нет в whales | JOIN не находит строку в `whales` | Соответствующий агрегат не записывается; ошибки нет; latent потеря (RF8) |
| UPDATE упал | Constraint violation, type mismatch | Транзакция функции откатывается полностью; `RETURN QUERY` не выполняется; bash `set -e` останавливает скрипт; `whales.last_pnl_updated` остаётся на момент **предыдущей** успешной итерации (RF5) |
| Падение между Step 2 (3B) и Step 3 (4) в bash | psql-таймаут, docker exec fail | Step 3 не запускается; `whale_trade_roundtrips` обновлены (3B успел закоммитить), `whales` агрегаты — устаревшие до следующей cron-итерации (RF2) |

---

## 11. Зависимости

### Upstream

- **Шаг 3B** (`settle_resolved_positions`) — закрывает OPEN-позиции в `whale_trade_roundtrips`, проставляет `net_pnl_usd`, переводит в `status='CLOSED'`. Без этого шага subquery вернёт 0 строк.
- **Шаг 3C** (DORMANT) — теоретический параллельный источник CLOSED-roundtrip-ов через SELL. В текущей топологии практически не материализуется.
- **Шаг 2A** (`whale_registration`) — создаёт строку в `whales` с `wallet_address`. Без записи в `whales` JOIN UPDATE-а не сработает (RF8).
- **`fetch_market_resolutions.py`** — косвенно, через 3B. На шаг 4 напрямую не влияет.

### Downstream

- **Governance-фаза** (вне магистрали) — оператор анализирует `whales.total_pnl_usd`, `win_rate_confirmed`, `total_roundtrips` и принимает решение об изменении `copy_status` (см. §14).
- **Materialized views** (`whale_pnl_summary`, `paper_simulation_pnl` — по `TEMPLATE_ANALYTICS_CHAT.md`) — обновляются на своём расписании, читают `whales` и `whale_trade_roundtrips`.
- **`whale_audit.sql`** — отчёт для governance, читает агрегаты из `whales`.

### External

Никаких external API. Только PostgreSQL внутри `polymarket_postgres`.

---

## 12. Наблюдаемость

### Логи

Один `echo` в bash с префиксом `[run_settlement] Whales updated: <N>` — в `settlement_cron.log`. Внутри SQL-функции собственного логирования (RAISE NOTICE и т.п.) нет.

### Метрики

Не экспортируются. Состояние агрегатов проверяется SELECT-запросом к `whales`:

```sql
SELECT wallet_address, total_pnl_usd, win_count, loss_count, win_rate_confirmed, last_pnl_updated
FROM whales
WHERE last_pnl_updated IS NOT NULL
ORDER BY last_pnl_updated DESC;
```

### Что наблюдатель НЕ видит

- Сколько новых CLOSED-roundtrip-ов появилось с прошлой итерации (нет дельты, всё в full recompute).
- Какие именно киты получили изменения агрегатов (только общее число обновлённых строк).
- Деградацию SQL-производительности при росте корпуса (нет тайминга).
- Расхождение между `whales.total_pnl_usd` и реальной суммой в `whale_trade_roundtrips`, если оно когда-либо возникнет (нет integrity-check).

---

## 13. Особые случаи и риски (RED FLAGs)

**RF1 [latent — scalability] — Full recompute каждые 2 часа.**
Каждый вызов пересчитывает агрегаты для **всех** китов с CLOSED-roundtrip-ами, независимо от того, появились ли новые закрытия. Функция поддерживает per-whale пересчёт через параметр `p_wallet_address`, но в production вызывается без аргумента (`run_settlement.sh:39`). На текущем корпусе работает; при росте числа китов × среднего числа закрытых позиций ожидается деградация. Сжатие таблицы через агрегацию рассматривается отдельно, вне скоупа pipeline_map.

**RF2 [architectural — материализован] — Race между шагом 3B и шагом 4 в одной cron-задаче.**
Шаги 3B и 4 выполняются как **две отдельные транзакции** через два независимых `docker exec psql -c` вызова (`run_settlement.sh:31-32, :38-39`). Между ними окно: если 3B успел закоммитить, а 4 упал (psql timeout, docker exec fail), `whale_trade_roundtrips` обновлены, `whales` агрегаты — устаревшие до следующей cron-итерации (≤2 часа). Атомарность шагов 3B+4 не гарантирована.

**RF3 [semantic] — break-even позиции классифицируются как loss.**
`COUNT(*) FILTER (WHERE net_pnl_usd <= 0)` (`migration_phase3_005:26`). Позиция с `net_pnl_usd = 0` (точно break-even, что возможно при `close_price == open_price`) попадает в `loss_count`. Влияет на `win_rate_confirmed` в сторону занижения. Для бинарного settlement break-even маловероятен (`close_price ∈ {0, 1}` ≠ обычные `open_price`), но для будущего корректного DIRECT_SELL — может материализоваться.

**RF4 [semantic] — имя `win_rate_confirmed` вводит в заблуждение.**
Subquery читает все `status = 'CLOSED'` независимо от `pnl_status` (`migration_phase3_005:30`). По DDL roundtrip `pnl_status IN ('CONFIRMED', 'ESTIMATED', 'UNAVAILABLE')`. Если в данных есть CLOSED-позиции с `pnl_status` ≠ `'CONFIRMED'`, их `net_pnl_usd` входит в агрегат. Имя `win_rate_confirmed` подразумевает фильтрацию по `pnl_status='CONFIRMED'`, которой фактически нет. Семантический расход между ожидаемым и фактическим поведением.

**RF5 [reliability] — Нет EXCEPTION block, `last_pnl_updated` не атомарен с агрегатами.**
В функции нет `EXCEPTION` блока (`migration_phase3_005:8-38`). Любая ошибка UPDATE-а откатывает всю транзакцию функции; `RETURN QUERY` не выполняется; bash `set -e` останавливает скрипт. `whales.last_pnl_updated` остаётся со значением **предыдущей** успешной итерации — внешний наблюдатель не сможет отличить «обновление прошло успешно 2 часа назад» от «последние 5 итераций упали, данные устаревают».

**RF6 [inherited from 3B] — Распространение искажений P&L из шага 3B.**
Шаг 4 берёт `net_pnl_usd` как готовое значение, не пересчитывает. Если на 3B сработал ARCH-003 (settlement затёр реальный SELL-выход бинарным close_price=0/1), искажённый `net_pnl_usd` попадает в `whales.total_pnl_usd` и `whales.win_rate_confirmed`. Шаг 4 — последняя точка денормализации искажения: дальше оно становится материалом для governance-решений.

**RF7 [operational] — Денормализация без trigger-консистентности.**
Если кто-то вручную UPDATE-ит `whale_trade_roundtrips.net_pnl_usd` (например, ручной фикс после расследования) или meняет `close_type` напрямую в БД, `whales.total_pnl_usd` останется устаревшим до следующего cron-запуска (до 2 часов). Trigger на `whale_trade_roundtrips AFTER UPDATE`, который запускал бы пересчёт, отсутствует.

**RF8 [latent — материализован условно] — NULL `wallet_address` в roundtrip и киты без записи в `whales`.**
- `GROUP BY wallet_address` соберёт все roundtrip-ы с `wallet_address IS NULL` в одну фантомную группу. Потом `WHERE w.wallet_address = sub.wallet_address` в PostgreSQL даёт `NULL = NULL → unknown → row excluded`. Фантомная группа просто не UPDATE-ит ничего. На практике маловероятно (на 3A `wallet_address` non-null по контракту), но latent.
- Симметричная проблема: если у кита есть CLOSED-roundtrip с заполненным `wallet_address`, но в `whales` нет соответствующей строки (теоретически — кит был exclude-нут оператором с DELETE вместо `copy_status='excluded'`), JOIN не сработает. Агрегат теряется без ошибки.

---

## 14. Результат шага

После успешного выполнения одной итерации `update_whale_pnl_from_roundtrips()`:

- Для каждого кита, у которого есть хотя бы один CLOSED-roundtrip, UPDATE-нуты все 7 P&L-полей `whales` (см. §9.3).
- Киты без CLOSED-roundtrip-ов не модифицируются — их P&L-поля остаются в default-состоянии (`0` / NULL).
- Сами roundtrip-ы не модифицируются (3A/3B/3C — единственные точки записи в `whale_trade_roundtrips`).
- `last_pnl_updated` отражает время этой итерации, не время последнего реального изменения данных кита.

**Состояние сделки/позиции в магистрали:** позиция кита достигла финального состояния несколькими шагами ранее (на 3B). На шаге 4 финальное состояние получает **сам кит** как агрегированная сущность: per-position P&L был зафиксирован в `whale_trade_roundtrips` (шаг 3B), агрегированный P&L кита теперь зафиксирован в `whales`.

### Связь со следующим шагом магистрали

**Магистраль одной сделки замыкается.** Дальнейшие state-изменения именно этой сделки или этой позиции магистраль не описывает — данные становятся read-only материалом для downstream-процессов.

**Бизнес-цикл проекта продолжается за пределами магистрали.** Агрегаты `whales` — это **вход для governance-фазы**, которая магистралью не покрыта:

- **Whale selection / promotion** — оператор анализирует `whales.total_pnl_usd`, `win_rate_confirmed`, `total_roundtrips` (плюс materialized view `whale_pnl_summary`) и принимает решение о смене `copy_status` (`none` → `tracked` → `paper`, или `→ excluded`). Решение реализуется ручным UPDATE `whales.copy_status` — этот UPDATE шагом 4 не выполняется и магистралью не описывается.
- **Paper-ветка copy trading** — для китов с `copy_status='paper'` каждая новая BUY-сделка запускает DB-trigger `trigger_copy_whale_trade` на шаге 2B, рождая запись в `paper_trades`. Это отдельная sidebar-магистраль (P1, P2, ...), вне основной нумерации 1–4.
- **Real execution (потенциальное будущее)** — `BuilderClient` (sidebar 1C, DORMANT) предназначен для перехода с paper на live trading.

Эти фазы — **не магистраль одной сделки**. Это **следующий контур** проекта: «после того как мы собрали данные о китах, мы решаем кого копировать и в каком режиме». Pipeline_map описывает только сбор и фиксацию данных одной сделки; governance, selection, copy execution описываются отдельными документами.

---

## 15. Краткая бизнес-формула шага

```
ВХОД: cron 0 */2 * * * → /root/polymarket-bot/scripts/run_settlement.sh
  │
  ├── Step 1 [не шаг 4] fetch_market_resolutions.py → market_resolutions
  ├── Step 2 [шаг 3B]   settle_resolved_positions() → UPDATE whale_trade_roundtrips
  │                                                    OPEN → CLOSED + net_pnl_usd
  │
  └── Step 3 [ШАГ 4] docker exec psql:
        SELECT updated_count FROM update_whale_pnl_from_roundtrips();
        │
        ├── UPDATE whales w
        │    SET win_count = sub.wins,
        │        loss_count = sub.losses,                  ← RF3 (break-even в losses)
        │        total_roundtrips = sub.total,
        │        total_pnl_usd = sub.total_pnl,
        │        avg_pnl_usd = sub.avg_pnl,
        │        win_rate_confirmed = wins / total,        ← RF4 (не фильтрует pnl_status)
        │        last_pnl_updated = NOW()                  ← RF5 (не атомарно с агрегатами при failure)
        │    FROM (
        │      SELECT wallet_address,
        │             COUNT(*) FILTER (net_pnl_usd > 0) AS wins,
        │             COUNT(*) FILTER (net_pnl_usd <= 0) AS losses,
        │             COUNT(*) AS total,
        │             COALESCE(SUM(net_pnl_usd), 0) AS total_pnl,
        │             COALESCE(AVG(net_pnl_usd), 0) AS avg_pnl
        │      FROM whale_trade_roundtrips
        │      WHERE status = 'CLOSED'                     ← без фильтра по pnl_status (RF4)
        │      GROUP BY wallet_address                     ← NULL-группа latent (RF8)
        │    ) sub
        │    WHERE w.wallet_address = sub.wallet_address   ← кит без записи в whales = потеря (RF8)
        │      AND (p_wallet_address IS NULL OR ...);      ← в production NULL, фильтр пассивен
        │
        ├── GET DIAGNOSTICS v_updated = ROW_COUNT;
        └── RETURN QUERY SELECT v_updated;

bash: UPDATED=$(...); echo "Whales updated: $UPDATED"; END.

ЧТО НЕ ОБНОВЛЯЕТСЯ на шаге 4:
  - copy_status, qualification_status, tier, whale_category  (governance)
  - total_trades, total_volume_usd, trades_last_*_days        (шаг 2A + activity cron)
  - estimated_capital, capital_estimation_method              (капиталометрия)
  - notes, whale_comment, exclusion_reason                    (operator-only)
  - whale_trade_roundtrips                                    (read-only для шага 4)

═════════════════════════════════════════════════════════════
МАГИСТРАЛЬ ОДНОЙ СДЕЛКИ ЗАМКНУЛАСЬ.

Данные whales → вход в governance-контур:
  • whale selection / copy_status promotion (оператор)
  • paper-ветка (P1, P2, ... — sidebar, INSERT в paper_trades через 2B trigger)
  • real execution (BuilderClient, DORMANT)

Эти фазы — не магистраль, описываются отдельными документами.
═════════════════════════════════════════════════════════════
```
