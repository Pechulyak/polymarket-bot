# PIPELINE_MAP_3C — roundtrip_close_sell

**Статус документа:** DORMANT-ветка магистрали; описание формата α
**Дата верификации:** 2026-05-15
**Эталон формата:** `PIPELINE_MAP_3B_close_settlement.md`

---

## TL;DR

Параллельная DORMANT-ветвь развилки шага 3: альтернативный механизм закрытия OPEN-roundtrip-ов через прямое сопоставление с SELL-событиями кита (вместо резолюции рынка через 3B). В текущем production не запускается ни одним runner-ом; метод `_close_roundtrips()` существует в `roundtrip_builder.py`, но активация требует CLI-флага `--close`, который не передаётся ни через docker-compose, ни через cron, ни через supervisor, ни через systemd. При гипотетической ре-активации обрабатывал бы все SELL-сделки кита, агрегируя их по `(wallet, market, outcome)`, искал бы соответствующий OPEN-roundtrip (exact match по `position_key` или fuzzy fallback по `wallet + market`), рассчитывал P&L и переводил roundtrip в `status='CLOSED'` с `close_type='SELL'`. После закрытия — инкрементально обновлял агрегаты P&L в `whales` через Python-метод `_update_whales_pnl()`, конкурирующий с SQL-функцией шага 4.

---

## 1. Назначение шага

Бизнес-смысл: зафиксировать факт **добровольного выхода кита из позиции** через продажу (SELL-событие), в отличие от шага 3B, где закрытие наступает автоматически после резолюции рынка. SELL-событие предполагает явное решение кита продать долю до момента settlement — это более ранний и более информативный сигнал о смене убеждения, чем пассивное ожидание резолюции.

В магистрали 3C — параллельная ветвь 3B; обе ведут к шагу 4 (обновление агрегатов `whales`). В текущем production магистраль закрывается исключительно через 3B; 3C — потенциально активируемая альтернатива.

---

## 2. Статус

**DORMANT в auto-pipeline** (верифицировано на 6 уровнях, 2026-05-15):

| Уровень | Проверка | Результат |
|---|---|---|
| Repo (grep) | `_close_roundtrips`, `run_close_positions`, `--close`, `RoundtripBuilder` | 0 production-вызовов |
| docker-compose | `command:` для всех сервисов | `roundtrip_builder` стартует без флагов → ветка `run()` (это шаг 3A) |
| Shell-скрипты | `scripts/*.sh` | `run_settlement.sh` вызывает `settle_resolved_positions()` и `update_whale_pnl_from_roundtrips()`, не `_close_roundtrips` |
| Cron (OS) | `crontab -l`, `/etc/cron.d/`, `/etc/crontab` | 7 задач, ни одна не содержит `--close` |
| Supervisor | `/etc/supervisor/conf.d/` | пусто |
| systemd | `systemctl list-units` | нет polymarket-сервисов |

Активация: только при ручном запуске `python -m src.strategy.roundtrip_builder --close` оператором, либо при добавлении флага в docker-compose / cron в рамках формальной ре-активации.

---

## 3. Исходные файлы

- `src/strategy/roundtrip_builder.py`:
  - `_fetch_and_group_sell_trades()` — строки 297–351
  - `_close_roundtrips()` — строки 353–470
  - `_update_whales_pnl()` — строки 472–573
  - `run_close_positions()` — обёртка, строки 892–939
  - CLI-роутинг `main()` — строки 1011–1032 (`--close` в строках 1016, 1027)
- `src/main.py:20,371` — импорт `RoundtripBuilder` закомментирован в рамках рефакторинга Phase 2B
- `scripts/smoke_test.sh:126` — тест ожидает FAIL импорта `RoundtripBuilder` (актуально для рефакторинга Phase 2B)
- DDL: `migration_whale_trade_roundtrips.sql` (целевая таблица), `scripts/init_db.sql` (whales)
- Конкурирующая SQL-функция шага 4: `scripts/migration_phase3_005_update_whale_pnl.sql:9-20`

---

## 4. Контейнер

`polymarket_roundtrip_builder` (docker-compose service `roundtrip_builder`). Контейнер тот же, что у шага 3A; различие — только в CLI-флаге.

Текущая `command:` контейнера:
```
sh -c "while true; do python -m src.strategy.roundtrip_builder; sleep 7200; done"
```

Для активации 3C потребовалось бы изменить команду на `python -m src.strategy.roundtrip_builder --close` или создать отдельный сервис / cron-задачу.

---

## 5. Триггер запуска и расписание

**В production отсутствует.** Технически возможный триггер — CLI-флаг `--close`, обрабатываемый в `main()` файла:

```
elif args.close:
    result = builder.run_close_positions()
```

(строка 1027). Без флага активируется ветка `else: builder.run(rebuild=args.rebuild)` — то есть шаг 3A.

Расписание при гипотетической ре-активации: не определено в коде. Метод `run_close_positions()` — однократный прогон, без внутреннего цикла; внешний loop (cron / while-loop) пришлось бы предоставить отдельно.

---

## 6. Алгоритм шага

Метод-обёртка `run_close_positions()` (строки 892–939) выполняет три последовательных шага с логированием границ через `logger("=" * 60)` и метки `[1/3]`, `[2/3]`, `[3/3]`. Возвращает итоговый словарь со счётчиками.

### 6.1 Шаг [1/3]: агрегация SELL-событий

Метод `_fetch_and_group_sell_trades()` выполняет один SQL-запрос к `whale_trades` с `LEFT JOIN whales` по нормализованному `wallet_address` (`LOWER`). Фильтр `WHERE wt.side = 'sell'`. Группировка по `(w.wallet_address, wt.market_id, wt.outcome, w.id)`. Агрегаты:
- `close_size_usd = SUM(wt.size_usd)`
- `close_price = SUM(price * size_usd) / NULLIF(SUM(size_usd), 0)` — взвешенное среднее
- `closed_at = MAX(wt.traded_at)` — момент последней продажи
- `close_trade_id = MAX(wt.id)` — ID последней сделки по `id`

Возвращает `Dict[position_key, aggregated_data]`. `position_key` генерируется на стороне Python через `_generate_position_key(wallet, market_id, outcome)`.

**Важное наблюдение:** темпоральный фильтр относительно `opened_at` соответствующего OPEN-roundtrip отсутствует. SELL-события агрегируются по всей истории `whale_trades`, включая возможные продажи, предшествующие открытию OPEN-позиции (см. §13, RF-001).

### 6.2 Шаг [2/3]: матчинг и UPDATE roundtrip-ов

Метод `_close_roundtrips(grouped_sells)` итерируется по записям из шага 6.1. Для каждой записи выполняет двухуровневый поиск OPEN-roundtrip:

**Exact match (первичный):**
```
SELECT id, whale_id, open_price, open_size_usd, status, outcome
FROM whale_trade_roundtrips
WHERE position_key = :position_key AND status = 'OPEN'
LIMIT 1
```

**Fuzzy fallback** (если exact ничего не вернул):
```
SELECT id, whale_id, open_price, open_size_usd, status, outcome
FROM whale_trade_roundtrips
WHERE wallet_address = :wallet_address
    AND market_id = :market_id
    AND status = 'OPEN'
ORDER BY opened_at DESC
LIMIT 1
```

Fuzzy явно **не фильтрует по `outcome`** — допускается матчинг SELL по `Yes` против OPEN по `No` того же кита и рынка (см. §13, RF-002). Сортировка `ORDER BY opened_at DESC LIMIT 1` берёт самую свежую OPEN-позицию без проверки релевантности (см. §13, RF-005).

Если оба поиска неуспешны — счётчик `skipped_count` инкрементируется, итерация переходит к следующей записи.

При найденном match вычисляется P&L:
- `gross_pnl = (close_price - open_price) * close_size`
- `fees_usd = 0` (литерал, нет источника данных по комиссиям)
- `net_pnl = gross_pnl - fees_usd`
- `pnl_status = 'CONFIRMED'` (литерал, без учёта различия exact/fuzzy)

UPDATE-statement модифицирует 14 колонок roundtrip-а (см. §9.1). Литералы:
- `close_side = 'sell'`
- `close_type = 'SELL'`
- `status = 'CLOSED'`
- `matching_method = 'FLIP'` (литерал для всех успехов, включая exact match — см. §13, RF-004)
- `matching_confidence = 'MEDIUM'` (литерал)

Защита от race: `WHERE id = :id AND status = 'OPEN'` — гарантирует, что параллельный UPDATE (например, шага 3B) не приведёт к повторному закрытию.

### 6.3 Шаг [3/3]: обновление агрегатов P&L в `whales` (Python-параллель шага 4)

Метод `_update_whales_pnl(closed_roundtrips)` принимает список успешно закрытых roundtrip-ов с уже посчитанным `net_pnl_usd`. Логика:

1. Группировка по `wallet_address`: подсчитывает `wins`, `losses`, `roundtrips`, `total_pnl` как **дельты** для каждого кошелька (только из текущего пакета, не из БД).
2. Для каждого `wallet_address` выполняет SELECT текущих значений `win_count, loss_count, total_roundtrips, total_pnl_usd` из `whales`.
3. Вычисляет новые значения **инкрементально**: `new = current + delta`.
4. Пересчитывает `avg_pnl_usd = new_total_pnl / new_total_roundtrips` и `win_rate_confirmed = new_win_count / new_total_roundtrips`.
5. UPDATE 8 колонок `whales` (см. §9.2).

**Принципиальное различие со SQL-функцией `update_whale_pnl_from_roundtrips()` шага 4:**
- Шаг 4 — **full recompute** из всех CLOSED-roundtrip-ов одним UPDATE-statement
- Шаг 3C `_update_whales_pnl` — **инкрементальный** UPDATE из дельт текущего пакета

При совместной активации обоих механизмов SQL-функция шага 4 полностью затирает результат Python-метода 3C при ближайшем cron-запуске (см. §13, RF-007 и RF-013).

---

## 7. Формат входных данных

### Из `whale_trades` (через `_fetch_and_group_sell_trades`)

Все SELL-сделки китов (`side='sell'`) без темпорального фильтра. Используются колонки: `id`, `wallet_address` (через JOIN из `whales`), `market_id`, `side`, `size_usd`, `price`, `outcome`, `traded_at`.

### Из `whale_trade_roundtrips` (через `_close_roundtrips`)

OPEN-roundtrip-ы (`status='OPEN'`). Используются колонки: `id`, `whale_id`, `open_price`, `open_size_usd`, `status`, `outcome`, `position_key`, `wallet_address`, `market_id`, `opened_at`.

### Из `whales` (через `_update_whales_pnl`)

Текущие значения P&L-агрегатов. Используются колонки: `wallet_address`, `win_count`, `loss_count`, `total_roundtrips`, `total_pnl_usd`.

---

## 8. Формат выходных данных

### Запись в `whale_trade_roundtrips`

Roundtrip переходит из `status='OPEN'` в `status='CLOSED'` с признаками:
- `close_type='SELL'` — отличает от `'SETTLEMENT_WIN'`/`'SETTLEMENT_LOSS'` шага 3B
- `close_side='sell'`
- `matching_method='FLIP'` — литерал для всех успехов
- `matching_confidence='MEDIUM'` — литерал
- `pnl_status='CONFIRMED'`

### Запись в `whales`

Обновлённые агрегаты P&L (инкрементально из дельт текущего пакета). См. §9.2.

### Возвращаемый словарь `run_close_positions()`

| Ключ | Тип | Источник |
|---|---|---|
| `sell_groups` | `int` | количество уникальных position_key с SELL-событиями |
| `closed` | `int` | количество успешно UPDATE-нутых roundtrip-ов |
| `skipped` | `int` | количество SELL-групп без OPEN-match |
| `whales_updated` | `int` | количество UPDATE-нутых записей в `whales` |
| `stats` | `Dict` | итоговая статистика `whale_trade_roundtrips` (status counts + total) |

---

## 9. Записи в БД

### 9.1 Таблица `whale_trade_roundtrips` — UPDATE через `_close_roundtrips`

DDL: `migration_whale_trade_roundtrips.sql`.

Все колонки изменяются **только на успешном пути** (после найденного exact или fuzzy match). На skipped-пути (ни один поиск не нашёл OPEN) — UPDATE не выполняется.

| Колонка | Тип / Default | Бизнес-смысл (5–6 слов) | Источник значения | Тип UPDATE |
|---|---|---|---|---|
| `close_trade_id` | `INTEGER REFERENCES whale_trades(id)` | ссылка на последнюю SELL-сделку | `MAX(wt.id)` из SELL-агрегации | UPDATE |
| `close_side` | `VARCHAR(10) CHECK IN ('buy','sell')` | сторона закрывающей сделки | литерал `'sell'` | UPDATE |
| `close_price` | `DECIMAL(20,8)` | взвешенная цена закрытия позиции | `SUM(price*size_usd)/SUM(size_usd)` из SELL | UPDATE |
| `close_size_usd` | `DECIMAL(20,8)` | суммарный объём закрытия в USD | `SUM(wt.size_usd)` из SELL | UPDATE |
| `closed_at` | `TIMESTAMP` | момент последней SELL-сделки | `MAX(wt.traded_at)` из SELL | UPDATE |
| `close_type` | `VARCHAR(50) CHECK IN (...)` | механизм закрытия позиции | литерал `'SELL'` | UPDATE |
| `status` | `VARCHAR(50) NOT NULL DEFAULT 'OPEN'` | жизненный статус roundtrip | литерал `'CLOSED'` | UPDATE |
| `gross_pnl_usd` | `DECIMAL(20,8)` | прибыль/убыток без комиссий | `(close_price - open_price) * close_size` | UPDATE |
| `fees_usd` | `DECIMAL(20,8) DEFAULT 0` | суммарные комиссии операции | литерал `0` (источника нет) | UPDATE |
| `net_pnl_usd` | `DECIMAL(20,8)` | итоговый P&L после комиссий | `gross_pnl - fees_usd` | UPDATE |
| `pnl_status` | `VARCHAR(50) DEFAULT 'UNAVAILABLE'` | уверенность в посчитанном P&L | литерал `'CONFIRMED'` | UPDATE |
| `matching_method` | `VARCHAR(50) CHECK IN (...)` | метод сопоставления open/close | литерал `'FLIP'` | UPDATE |
| `matching_confidence` | `VARCHAR(20) CHECK IN (...)` | уверенность в сопоставлении | литерал `'MEDIUM'` | UPDATE |
| `updated_at` | `TIMESTAMP NOT NULL DEFAULT NOW()` | момент последнего изменения | `NOW()` | UPDATE |

**Сохраняются (не изменяются):** `id`, `whale_id`, `wallet_address`, `position_key`, `market_id`, `outcome`, `market_title`, `market_category`, `open_trade_id`, `open_side`, `open_price`, `open_size_usd`, `opened_at`, `paper_trade_id`, `created_at` — поля, принадлежащие фазе OPEN или governance-фазе вне ответственности шага 3C.

**UPDATE блокируется полностью**, если параллельный процесс уже перевёл roundtrip в `status != 'OPEN'`: WHERE-условие `WHERE id = :id AND status = 'OPEN'` не пройдёт, `rowcount = 0`, roundtrip не попадёт в `closed_roundtrips` и не повлияет на §9.2.

### 9.2 Таблица `whales` — UPDATE через `_update_whales_pnl`

DDL: `scripts/init_db.sql` (блок «P&L fields», ARC-501).

| Колонка | Тип / Default | Бизнес-смысл (5–6 слов) | Источник значения | Тип UPDATE |
|---|---|---|---|---|
| `win_count` | `INTEGER NOT NULL DEFAULT 0` | количество прибыльных закрытых позиций | `current_win_count + data['wins']` (инкрементально) | UPDATE |
| `loss_count` | `INTEGER NOT NULL DEFAULT 0` | количество убыточных закрытых позиций | `current_loss_count + data['losses']` (инкрементально) | UPDATE |
| `total_roundtrips` | `INTEGER NOT NULL DEFAULT 0` | всего завершённых позиций кита | `current_total_roundtrips + data['roundtrips']` (инкрементально) | UPDATE |
| `total_pnl_usd` | `DECIMAL(20,8) NOT NULL DEFAULT 0` | суммарный P&L кита в USD | `current_total_pnl + data['total_pnl']` (инкрементально) | UPDATE |
| `avg_pnl_usd` | `DECIMAL(20,8) NOT NULL DEFAULT 0` | средний P&L на одну позицию | `new_total_pnl / new_total_roundtrips` (пересчёт) | UPDATE |
| `win_rate_confirmed` | `DECIMAL(5,4) NOT NULL DEFAULT 0` | доля прибыльных позиций кита | `new_win_count / new_total_roundtrips` (пересчёт) | UPDATE |
| `last_pnl_updated` | `TIMESTAMP` (nullable) | момент последнего пересчёта P&L | `NOW()` | UPDATE |
| `updated_at` | `TIMESTAMP NOT NULL DEFAULT NOW()` | момент последнего изменения | `NOW()` | UPDATE |

**Сохраняются (не изменяются):** все governance-поля (`copy_status`, `tier`, `qualification_status`, `whale_category`, `whale_comment`, `reviewed_at`, `exclusion_reason`, `estimated_capital`), discovery-поля, `wallet_address`, `id`, `created_at`. Шаг 3C — write-only для P&L-блока.

**UPDATE блокируется полностью**, если SELECT по `wallet_address` ничего не вернул (строка 524, `if not row: continue`). То есть SELL-события китов, не зарегистрированных в `whales`, в §9.2 не приводят ни к какому UPDATE.

---

## 10. Условия успеха / частичного успеха / неуспеха

### Успех (на уровне одной SELL-группы)

`closed_count += 1`. Достигается при выполнении всех условий:
1. Найден OPEN-roundtrip через exact match (`position_key`) ИЛИ через fuzzy fallback (`wallet + market`).
2. UPDATE `whale_trade_roundtrips` вернул `rowcount > 0` (т.е. roundtrip всё ещё был в `status='OPEN'` на момент UPDATE).

После успеха запись добавляется в `closed_roundtrips`, передаётся в `_update_whales_pnl()` для обновления агрегатов `whales`.

### Частичный успех

Не различается на уровне отдельной SELL-группы — у метода нет статуса `PARTIAL` в результатах (хотя DDL `whale_trade_roundtrips` его поддерживает). На уровне всей итерации `run_close_positions()` частичный успех возможен в смысле «N закрыто, M пропущено» — фиксируется в `closed_count` vs `skipped_count`.

### Неуспех

`skipped_count += 1`. Достигается, если ни exact match, ни fuzzy fallback не нашли OPEN-roundtrip. SELL-группа отбрасывается без побочных эффектов: ни UPDATE в `whale_trade_roundtrips`, ни UPDATE в `whales`. Список `skipped_keys` собирается локально, но не сохраняется и не логируется поэлементно — только итоговый счётчик.

Возможен также неуспех на этапе `_update_whales_pnl`, если `wallet_address` не найден в `whales`: SELL-сделка orphaned (без зарегистрированного кита). UPDATE `whale_trade_roundtrips` уже состоялся, агрегаты `whales` не обновляются. Сборка лога / уведомления об orphaned-кейсе отсутствует.

---

## 11. Зависимости

### Upstream

- **Шаг 3A** (`roundtrip_open`) — создаёт OPEN-roundtrip-ы в `whale_trade_roundtrips`, которые 3C закрывает.
- **Шаг 2B** (`whale_trades_write`) — пишет SELL-сделки в `whale_trades`, которые 3C агрегирует.
- **Шаг 2A** (`whale_registration`) — обеспечивает наличие кита в `whales` для `_update_whales_pnl` (через `wallet_address` lookup).

### Downstream

- **Шаг 4** — SQL-функция `update_whale_pnl_from_roundtrips()` читает CLOSED-roundtrip-ы (включая закрытые через 3C) для полного пересчёта агрегатов `whales`. **Конкурирует с `_update_whales_pnl()` 3C** (см. §13, RF-007, RF-013).
- `src/data/storage/category_backfill.py:274,360` — backfill `market_category` сканирует `whale_trade_roundtrips` без фильтра по `status` или `close_type`; на 3C не зависит, но потребляет результат.
- `src/strategy/whale_roundtrip_reconstructor.py` — dead duplicate (см. §13, RF-010); не вызывается в production.

### External services

Ни одного. 3C — чисто внутренний SQL-процесс без обращений к Polymarket API, CLOB, Gamma. Это отличает 3C от 3B, где требуется `market_resolutions` (заполняется отдельным скриптом).

### Параллельная ветка

- **Шаг 3B** (`close_settlement`) — обрабатывает те же OPEN-roundtrip-ы через резолюцию рынка вместо SELL. Защита от двойного закрытия — `WHERE status = 'OPEN'` в UPDATE-statement обоих шагов; параллельный запуск возможен, но какой-то из двух не пройдёт (или 3C, или 3B), не оба.

---

## 12. Наблюдаемость

### Логи

14 `logger()` вызовов, все внутри обёртки `run_close_positions()` (строки 900–931). Маркер `ROUNDTRIP BUILDER (ARC-502-B) - Closing Positions`. Структура: 3 шага с метками `[1/3]`, `[2/3]`, `[3/3]` + итоговый блок «Results» со счётчиками `sell_groups`, `closed`, `skipped`, `whales_updated`, `stats`.

**Все логи — уровень `info`.** Уровней `warning` / `error` метод не использует.

**Внутри `_fetch_and_group_sell_trades`, `_close_roundtrips`, `_update_whales_pnl` — ноль логов.** Любая ошибка SQL / матчинга / orphaned-кита уходит в обычный stack trace без бизнес-контекста (см. §13, RF-012).

### Метрики

Не публикуются. `pipeline_monitor` (cron `*/30`) не отслеживает шаг 3C, так как тот не запускается.

### Heartbeat

`run_close_positions()` **не пишет** `/tmp/heartbeat`. Heartbeat-логика есть только в `run()` (шаг 3A, строки ~996–1001).

**Следствие ре-активации:** если активировать `--close` в текущем docker-compose сервисе `roundtrip_builder` без модификации healthcheck-логики, контейнер будет помечен `unhealthy` через 10 минут после запуска (`test -f /tmp/heartbeat && find /tmp/heartbeat -mmin -10`). С `restart: always` это вызовет авторестарт цикла. См. §13, RF-011.

### Алерты

Отсутствуют для 3C. `Daily Whale Alert Monitor`, `Weekly AI whale analysis` потребляют итоговые агрегаты `whales`, но не различают источник (3B vs 3C).

---

## 13. Особые случаи и риски (RED FLAGs)

Метод DORMANT — все риски ниже не материализуются в production. При ре-активации каждый требует решения (см. §16).

| ID | Источник | Описание |
|---|---|---|
| RF-001 | BUG-608 CODE-001 | В `_fetch_and_group_sell_trades` нет темпорального фильтра. SELL, произошедший до OPEN, может закрыть OPEN — формально нарушает причинность. |
| RF-002 | BUG-608 CODE-002 | Fuzzy fallback не фильтрует по `outcome`. SELL по `Yes` может закрыть OPEN по `No` того же кита и рынка. `pnl_status='CONFIRMED'` ставится без понижения уверенности для fuzzy. |
| RF-003 | BUG-608 CODE-003 | `closed_at = MAX(traded_at)` и `close_trade_id = MAX(wt.id)` — независимые агрегации. При ретро-импорте порядок `id` может не совпадать с порядком `traded_at`, ссылка `close_trade_id` указывает не на ту сделку. |
| RF-004 | BUG-608 CODE-004 | `matching_method='FLIP'` и `matching_confidence='MEDIUM'` — литералы для всех успехов, включая exact match. Поля бесполезны для последующей фильтрации. |
| RF-005 | BUG-608 CODE-005 | Fuzzy `ORDER BY opened_at DESC LIMIT 1` берёт самую свежую OPEN-позицию. При наличии нескольких OPEN на одном рынке (разные `outcome`) выбор произвольный, без проверки релевантности. |
| RF-006 | TP-3 | `fees_usd = 0` хардкодом. `gross_pnl_usd = net_pnl_usd` всегда. Аналогично 3B, но фиксируется для checklist. |
| RF-007 | TP-3, TP-4 | `_update_whales_pnl` (Python, инкрементальный) и `update_whale_pnl_from_roundtrips()` шага 4 (SQL, full recompute) пишут в **те же 7 колонок** `whales`. При параллельной активации возникает race-condition. |
| RF-008 | TP-4 | `_update_whales_pnl` пишет `updated_at`; SQL-функция шага 4 — нет. Расхождение схем влияет на consumers, фильтрующих по `updated_at`. |
| RF-009 | forensics | Ветка `--close` могла быть выведена из production не намеренно, а как побочный эффект рефакторинга Phase 2B (закомментирование `RoundtripBuilder` в `main.py`, `smoke_test.sh:126` ожидает FAIL импорта). 530 SELL-roundtrip-ов в БД (из BUG-608) — возможные legacy-данные периода, когда `--close` ещё работал. Открытый вопрос; вне скоупа 3C. |
| RF-010 | architectural | `whale_roundtrip_reconstructor.py` — dead duplicate с альтернативной формулой `position_key` (`hash(wallet + market_id + outcome + open_trade_id)` vs `hash(wallet + market_id + outcome)` у `roundtrip_builder`). При случайной ре-активации обоих модулей формулы разойдутся. |
| RF-011 | TP-4 | `run_close_positions()` не пишет `/tmp/heartbeat`. Docker healthcheck сервиса `roundtrip_builder` упадёт через 10 минут после старта `--close`-режима. С `restart: always` — авторестарт. |
| RF-012 | TP-4 | Внутри `_close_roundtrips`, `_fetch_and_group_sell_trades`, `_update_whales_pnl` — ноль логов. Ошибки SQL / матчинга / orphaned-кошельков уходят в stack trace без бизнес-контекста. Наблюдаемость DORMANT-ветки при ре-активации — на минимуме. |
| RF-013 | TP-4 | Усиление RF-007. SQL-функция шага 4 делает full-replace из всех CLOSED-roundtrip-ов (включая 3B). Python-метод 3C — инкрементальное `current + delta`. Между UPDATE Python и cron SQL (окно до 2 часов) consumers `whales.total_pnl_usd` видят inconsistent intermediate state. |

---

## 14. Результат шага

### Достигнутое состояние roundtrip

Roundtrip переходит из `OPEN` в `CLOSED` с признаком `close_type='SELL'`, отличающим его от `'SETTLEMENT_WIN'`/`'SETTLEMENT_LOSS'` шага 3B. P&L посчитан и зафиксирован.

### Достигнутое состояние кита

Агрегаты `whales` (`win_count`, `loss_count`, `total_roundtrips`, `total_pnl_usd`, `avg_pnl_usd`, `win_rate_confirmed`, `last_pnl_updated`, `updated_at`) инкрементально обновлены на дельту текущего пакета SELL-закрытий.

### Связь со следующим шагом магистрали

3C — параллельная ветвь 3B; обе ведут к одной развязке — **шагу 4** (`update_whale_pnl_from_roundtrips`). Однако:

- При ре-активации **без отключения** cron Step 3 `run_settlement.sh`: результат `_update_whales_pnl` 3C перезаписывается SQL-функцией шага 4 в течение ≤2 часов через full recompute. Конечное состояние `whales` корректно (включает все CLOSED-roundtrip-ы), но промежуточное окно расходится.
- При ре-активации **с отключением** cron Step 3: `_update_whales_pnl` 3C становится единственным механизмом для P&L-агрегатов **по SELL-закрытиям**, но не охватывает SETTLEMENT-закрытия шага 3B (которые перестают пересчитываться). Это нарушит корректность агрегатов.
- Корректный сценарий ре-активации: оставить SQL-функцию шага 4 единственным источником истины для агрегатов `whales`, удалить `_update_whales_pnl` из `run_close_positions` или сделать его no-op.

См. §16.

---

## 15. Краткая бизнес-формула шага (ASCII)

```
┌──────────────────────────────────────────────────────────────┐
│ ШАГ 3C — roundtrip_close_sell (DORMANT)                      │
│                                                              │
│ Триггер: НЕ ЗАПУСКАЕТСЯ В PRODUCTION                         │
│ Гипотетический: python -m src.strategy.roundtrip_builder     │
│                 --close                                       │
│                                                              │
│ [1/3] _fetch_and_group_sell_trades                           │
│   whale_trades (side='sell') → GROUP BY wallet+market+outcome│
│   → Dict[position_key, {close_price, close_size, ...}]       │
│                                                              │
│ [2/3] _close_roundtrips                                      │
│   for each SELL-group:                                       │
│     exact match (position_key) → fuzzy (wallet+market)       │
│     → no match: skipped                                      │
│     → match: P&L calc, UPDATE roundtrip                      │
│             (status=CLOSED, close_type=SELL,                 │
│              matching_method=FLIP)                           │
│                                                              │
│ [3/3] _update_whales_pnl  ⚠ КОНКУРИРУЕТ СО ШАГОМ 4           │
│   incremental: current + delta                                │
│   UPDATE whales (win_count, loss_count, total_roundtrips,    │
│                  total_pnl_usd, avg_pnl_usd,                 │
│                  win_rate_confirmed, last_pnl_updated,       │
│                  updated_at)                                  │
└──────────────────────────────────────────────────────────────┘
```

---

## 16. Pre-flight checklist и варианты решения при ре-активации

Раздел является продолжением §13 — для каждого RF указано минимально необходимое решение перед ре-активацией.

### 16.1 Обязательные блокеры (без исправления — ре-активация запрещена)

**B1. Race с SQL-функцией шага 4 (RF-007, RF-013).**
Варианты:
- **(a)** Удалить вызов `self._update_whales_pnl(closed_roundtrips)` из `run_close_positions()` строка 916. Единственный источник истины для `whales` P&L — SQL-функция шага 4. Минимально инвазивно.
- **(b)** Отключить cron Step 3 в `run_settlement.sh` на время работы 3C, синхронизировать запуск 3C и 3B. Сложнее; увеличивает связность.
- **Рекомендация:** (a). Python-метод `_update_whales_pnl` сохранить как мёртвый код или удалить целиком вместе с RF-008.

**B2. Heartbeat (RF-011).**
Варианты:
- **(a)** Добавить запись `/tmp/heartbeat` в конце `run_close_positions()` по образцу `run()` (строки ~996–1001).
- **(b)** Создать отдельный docker-compose сервис `roundtrip_closer` с отдельным healthcheck.
- **Рекомендация:** (a). Минимальное изменение, согласованное с существующим сервисом.

### 16.2 Корректность логики (требуют решения до ре-активации)

**C1. Темпоральный фильтр (RF-001).**
Добавить в `_fetch_and_group_sell_trades` JOIN с `whale_trade_roundtrips` по `position_key` и фильтр `WHERE wt.traded_at > rt.opened_at`. Без этого — формально некорректное закрытие.

**C2. Fuzzy по outcome (RF-002, RF-005).**
Варианты:
- **(a)** Полностью убрать fuzzy fallback. Все SELL без exact match → skipped.
- **(b)** Оставить fuzzy, но добавить `AND outcome = :outcome` и `pnl_status='ESTIMATED'`, `matching_confidence='LOW'`.
- **Рекомендация:** (a). Fuzzy fallback в текущем виде создаёт больше шума, чем сигнала.

**C3. `MAX(id)` vs `MAX(traded_at)` (RF-003).**
Заменить агрегацию `close_trade_id = MAX(wt.id)` на оконную функцию: выбрать `id` той сделки, у которой `traded_at = MAX(traded_at)` в группе. Один subquery / window function.

### 16.3 Метаданные и наблюдаемость (желательны до ре-активации)

**M1. Метаданные матчинга (RF-004).**
Различать литералы в UPDATE по ветке:
- exact match → `matching_method='DIRECT_SELL'`, `matching_confidence='HIGH'`
- fuzzy (если оставлен) → `matching_method='FUZZY_FLIP'`, `matching_confidence='LOW'`

**M2. Логирование (RF-012).**
Добавить `logger.info` / `logger.warning` внутри `_close_roundtrips` для случаев:
- fuzzy fallback использован
- roundtrip skipped (с position_key)
- orphaned wallet в `_update_whales_pnl` (нет в `whales`)

### 16.4 Архитектурные риски (фиксация, не блокер)

**A1. Dead duplicate (RF-010).**
`whale_roundtrip_reconstructor.py` — отдельная задача аудита/удаления. Не блокирует 3C, но создаёт риск случайной активации с расходящейся формулой `position_key`. Рекомендация: удалить файл или явно пометить `DEPRECATED` в комментарии модуля.

**A2. Forensics 530 SELL-roundtrip-ов (RF-009).**
Перед ре-активацией провести `git log` по `src/main.py` и `scripts/smoke_test.sh` на дату Phase 2B; восстановить причину закомментирования `RoundtripBuilder`. Без этого — риск повторить ранее устранённую проблему.

### 16.5 Минимальный набор изменений для безопасной ре-активации

1. Удалить вызов `_update_whales_pnl` из `run_close_positions` (B1.a).
2. Добавить heartbeat (B2.a).
3. Добавить темпоральный фильтр в SQL (C1).
4. Убрать fuzzy fallback (C2.a).
5. Заменить агрегацию `close_trade_id` на window function (C3).
6. Раскомментировать импорт `RoundtripBuilder` в `src/main.py`, обновить `smoke_test.sh:126` (рефакторинг Phase 2B).
7. Изменить `command:` в `docker-compose.yml` для `roundtrip_builder` или создать отдельный сервис с `--close`.

После 1–7 — DRY-run на staging БД, верификация corner-cases (orphaned wallets, race с 3B), включение в production с мониторингом.
