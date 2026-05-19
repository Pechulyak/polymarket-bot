# ШАГ 3A. СОЗДАНИЕ OPEN-ROUNDTRIP ИЗ BUY-СДЕЛОК

## Краткая характеристика (TL;DR)

Шаг 3 магистрали разделён на три параллельные ветви по типу действия над `whale_trade_roundtrips`:

- **Шаг 3A** — создание новых OPEN-позиций из BUY-сделок (этот документ).
- **Шаг 3B** — закрытие OPEN-позиций через резолюцию рынка (settlement, ACTIVE, описан отдельно).
- **Шаг 3C** — закрытие OPEN-позиций через SELL-события (DORMANT в auto-pipeline, описан отдельно).

### Шаг 3A в бизнес-нотации

Раз в 2 часа отдельный контейнер `roundtrip_builder` сканирует все BUY-сделки китов в таблице `whale_trades` без временного окна, агрегирует их по тройке `(wallet_address, market_id, outcome)` и для каждой ранее не виденной тройки создаёт OPEN-roundtrip в `whale_trade_roundtrips` — единую запись, объединяющую все BUY-сделки кита по этой позиции (суммарный размер, средневзвешенная цена, время первой покупки). BUY-сделки одного кита с одинаковыми `(market_id, outcome)` сворачиваются в одну позицию; сделки, различающиеся хотя бы по одному из трёх полей, формируют разные позиции.

---

## 1. Назначение шага

Шаг переводит сырые BUY-события из `whale_trades` (per-event) в **открытые торговые позиции** (per-position) — необходимый агрегат для последующего расчёта P&L после закрытия. Без этого шага каждая BUY-сделка существует как изолированное событие; closure-логика (шаги 3B и 3C) работает только с уже созданными OPEN-roundtrip-ами и без них не имеет якоря.

Бизнес-смысл: «получили N BUY-событий по позиции → собрали из них одну открытую позицию с агрегированными показателями».

---

## 2. Статус

**CONFIRMED-ACTIVE.** Контейнер `roundtrip_builder` запущен через docker-compose, выполняется бесконечный цикл `python -m src.strategy.roundtrip_builder` + `sleep 7200`. Без аргументов командной строки вызывается `builder.run(rebuild=False)` (`roundtrip_builder.py:1011–1032`), который запускает только BUY-build без вызовов close / settle / update_pnl (`roundtrip_builder.py:941–1008`).

Дата верификации: 2026-05-11.

---

## 3. Исходные файлы

**Точка входа:**
- `src/strategy/roundtrip_builder.py` — модуль `RoundtripBuilder`, метод `run()` (`:941–1008`), `main()` (`:1011–1032`).

**Используемые методы класса:**
- `_fetch_and_group_buy_trades()` (`:98–141`) — SQL-выборка и группировка
- `_get_existing_open_position_keys()` (`:966`) — read-only diagnostic
- `_create_roundtrips()` (`:175–228`) — построение dict для INSERT
- `_save_roundtrips()` (`:242–270`) — построчный INSERT с ON CONFLICT
- `_get_statistics()` (`:984`) — read-only summary
- `_generate_position_key()` (`:73–84`) — формула ключа группировки

**DDL целевой таблицы:**
- `scripts/migration_whale_trade_roundtrips.sql:6–105` — CREATE TABLE + constraints + indexes.

**Источник BUY-событий:**
- Таблица `whale_trades`, заполняемая шагом 2B. См. перекрёстный раздел в §11.

---

## 4. Контейнер

`roundtrip_builder` — отдельный docker-compose сервис (`docker-compose.yml:171–203`). Build из `docker/Dockerfile`. Команда запуска — inline shell-loop без cron / supervisord внутри:

```yaml
command: >
  sh -c "while true; do
    python -m src.strategy.roundtrip_builder;
    sleep 7200;
  done"
```

Volume `roundtrip_heartbeat:/tmp` — для heartbeat-файла. Restart policy `always`. Healthcheck `test -f /tmp/heartbeat && find /tmp/heartbeat -mmin -10` каждые 120 секунд.

Контейнер изолирован от `bot` и `whale-detector`: не разделяет ни in-memory state, ни обёртки шага 2B.

---

## 5. Триггер запуска и расписание

| Параметр | Значение | Источник |
|----------|----------|----------|
| Тип триггера | inline shell `while true; do ... sleep 7200; done` | `docker-compose.yml:180–184` |
| Период | 7200 секунд = 2 часа | `docker-compose.yml:183` |
| Аргументы CLI в production | НЕТ (запуск `python -m src.strategy.roundtrip_builder` без флагов) | `docker-compose.yml:182` |
| Code path при отсутствии флагов | `builder.run(rebuild=False)` | `roundtrip_builder.py:1029–1030` |
| Альтернативные CLI-режимы | `--rebuild`, `--close`, `--settle` (существуют, в production не используются) | `roundtrip_builder.py:1013–1028` |

Расписание не координируется с `run_settlement.sh` (cron 2h, шаг 3B): два независимых процесса с одинаковым периодом, но без синхронизации старта. Race-условие фиксируется как RED FLAG в шаге 3B.

---

## 6. Алгоритм шага

### 6.1 Точка входа

`__main__` → `main()` → argparse (без флагов) → `builder.run(rebuild=False)` (`roundtrip_builder.py:1029–1030`).

### 6.2 Тело `run(rebuild=False)` — 4 логических блока

Последовательность по `roundtrip_builder.py:941–1008`:

1. **Fetch & group BUY events** (`:954–957`)
   - Вызов `_fetch_and_group_buy_trades()` → `Dict[position_key → trade_data]`
   - Лог: `[1/4] Found N unique position groups`

2. **Check existing OPEN roundtrips** (`:959–967`) — diagnostic-only
   - При `rebuild=False`: вызов `_get_existing_open_position_keys()` → `existing_keys`
   - Лог: `[2/4] Found M existing OPEN roundtrips`
   - **Результат не используется для фильтрации** (см. RF2 в §13)

3. **Create roundtrip records** (`:969–972`)
   - Вызов `_create_roundtrips(grouped_trades)` → `(roundtrips, created)`
   - Каждый element в `roundtrips` — dict из 27 ключей (см. §9)

4. **Save to database** (`:974–981`)
   - При `roundtrips` непустом: вызов `_save_roundtrips(roundtrips)`
   - Лог: `[4/4] Saved S records` (S = `len(roundtrips)`, не rowcount; RF3)

5. **Finalization** (`:983–1007`)
   - `_get_statistics()` — read-only summary
   - Heartbeat file write `/tmp/heartbeat` (try/except, non-critical)
   - Return dict с `buy_groups`, `created`, `saved`, `stats`

### 6.3 `_fetch_and_group_buy_trades()` — SQL + Python группировка

**SQL (`roundtrip_builder.py:98–115`):**

SELECT по `whale_trades wt` с `LEFT JOIN whales w` по нормализованному `LOWER(wallet_address)`. Фильтр `WHERE wt.side = 'buy'` — SELL-события на 3A игнорируются. `GROUP BY w.wallet_address, wt.market_id, wt.outcome, w.id` — ключ группировки. `ORDER BY opened_at`. Возвращаемые колонки на группу: `wallet_address`, `market_id`, `outcome`, `SUM(size_usd)`, средневзвешенная цена `SUM(price·size_usd) / NULLIF(SUM(size_usd), 0)`, `MIN(traded_at)`, `MIN(id)`, `w.id`.

Ключевые свойства запроса:
- `WHERE wt.side = 'buy'` — SELL-события на этом шаге игнорируются.
- Нет временного фильтра (`traded_at`-условие отсутствует) — каждая итерация сканирует **всю** `whale_trades` (RF5).
- `LEFT JOIN whales` сохраняет строки `whale_trades` с `whale_id IS NULL` (RF8).
- Aggregate: суммарный размер, средневзвешенная цена, минимальная (первая) дата покупки, ID первой покупки.

**Python-группировка (`roundtrip_builder.py:119–141`):**

Итерация по cursor.result. На каждой строке вызывается `_generate_position_key(wallet, market, outcome)` для построения ключа. Результат сохраняется в `grouped[position_key]` как dict с полями: `whale_id` (из `w.id`, может быть None), `wallet_address`, `position_key`, `market_id`, `outcome`, `open_size_usd`, `open_price`, `opened_at`, `open_trade_id`, `market_title=None` (литерал, в SQL не выбирается). Структура передаётся дальше в `_create_roundtrips()`.

### 6.4 `_generate_position_key()` — формула ключа

`roundtrip_builder.py:73–84`:

```python
def _generate_position_key(self, wallet_address: str, market_id: str, outcome: str = None) -> str:
    return f"{wallet_address}:{market_id}:{outcome or 'unknown'}"
```

Plain string, без хеширования (sha256/md5 не используются). При `outcome=None` — fallback на literal `'unknown'`. Параллельный модуль `whale_roundtrip_reconstructor.py` использует sha256 от тех же полей плюс `open_trade_id` — несовместимая формула (см. RF7).

### 6.5 `_create_roundtrips()` — построение dict для INSERT

`roundtrip_builder.py:175–228` строит для каждой группы dict из 27 ключей. Все open-поля заполняются из `trade_data`; все close-поля и P&L-поля — `None`; `status='OPEN'` проставляется явно. Полный перечень — в §9.

### 6.6 `_save_roundtrips()` — INSERT в БД

`roundtrip_builder.py:242–270`. Готовится один параметризованный INSERT-запрос для таблицы `whale_trade_roundtrips` со всеми 27 колонками (`id`, `whale_id`, `wallet_address`, `position_key`, `market_id`, `outcome`, `market_title`, `market_category`, 5 open-полей, 5 close-полей, `close_type`, `status`, 4 pnl-поля, `matching_method`, `matching_confidence`, `created_at`, `updated_at`). Значения `created_at` и `updated_at` проставляются как `NOW()` на стороне SQL. Запрос завершается clause `ON CONFLICT (position_key) DO NOTHING` — конфликт на UNIQUE-индексе обрабатывается silent skip без UPDATE.

Исполнение: `with self._engine.connect() as conn:` → цикл `for rt in roundtrips:` с `conn.execute(query, rt)` на каждую запись → один `conn.commit()` после цикла. Метод возвращает `len(roundtrips)`.

Свойства реализации:
- Построчный `execute` в цикле, без `executemany`.
- Один `commit()` после цикла — все INSERT в одной транзакции.
- `ON CONFLICT (position_key) DO NOTHING` — silent skip любого дубликата, независимо от status существующей записи (RF1).
- Return `len(roundtrips)` — счётчик переданных, не фактически вставленных (RF3).
- Нет try/except — ошибка любого `execute` откатывает всю партию (RF9).

---

## 7. Формат входных данных

Все BUY-сделки таблицы `whale_trades`, заполненной шагом 2B. Контракт описан в шаге 2B §9. Шаг 3A читает 6 колонок: `wallet_address`, `market_id`, `outcome`, `side` (фильтр), `size_usd`, `price`, `traded_at`, `id`. Колонки `tx_hash`, `whale_id` (как FK), `market_title`, `market_category`, `source` шагом 3A не используются для агрегации.

`whale_id` подтягивается JOIN-ом к `whales`, не из `whale_trades.whale_id`.

---

## 8. Формат выходных данных

Записи в таблице `whale_trade_roundtrips` со `status='OPEN'`. Полный перечень колонок — в §9. Шаг возвращает в caller dict со счётчиками `buy_groups`, `created`, `saved`, `stats` — используется только для логирования внутри контейнера, наружу не экспортируется.

---

## 9. Записи в БД

### 9.1 Целевая таблица

`whale_trade_roundtrips`. DDL — `scripts/migration_whale_trade_roundtrips.sql:6–86`.

Constraints:
- `PRIMARY KEY (id)`
- **`UNIQUE NOT NULL (position_key)`** — `migration_whale_trade_roundtrips.sql:15`
- `NOT NULL`: `opened_at`, `status`, `created_at`, `updated_at`
- `CHECK status IN ('OPEN', 'CLOSED', 'PARTIAL', 'FLIPPED', 'UNRESOLVED')`
- `CHECK open_side IN ('buy', 'sell')`
- `FK whale_id → whales(id)`
- `FK open_trade_id → whale_trades(id)`
- `FK close_trade_id → whale_trades(id)`
- `FK paper_trade_id → trades(trade_id)` (RF4 — ссылка на `trades`, не `paper_trades`)

Indexes — `migration_whale_trade_roundtrips.sql:88–105` (8 индексов, перечислены в исходном отчёте Roo).

### 9.2 Операция шага: INSERT ON CONFLICT DO NOTHING

Шаг 3A выполняет только INSERT. UPDATE существующих строк — НЕ выполняет (это закрытие, шаги 3B/3C).

### 9.3 Колонки, записываемые шагом 3A

| # | Колонка | Бизнес-смысл (5–6 слов) | Источник значения |
|---|---------|--------------------------|-------------------|
| 1 | `id` | уникальный идентификатор записи roundtrip | `uuid4()` в `_create_roundtrips:184` |
| 2 | `whale_id` | FK на каталог китов (может быть NULL) | `w.id` из LEFT JOIN; NULL для незарегистрированных |
| 3 | `wallet_address` | адрес кошелька кита позиции | `whale_trades.wallet_address` через `whales.wallet_address` |
| 4 | `position_key` | уникальный ключ позиции для dedup | `f"{wallet}:{market}:{outcome or 'unknown'}"` |
| 5 | `market_id` | идентификатор рынка Polymarket | `whale_trades.market_id` |
| 6 | `outcome` | исход рынка по которому позиция | `whale_trades.outcome` (нормализованный в 2B) |
| 7 | `market_title` | человекочитаемое название рынка | **`NULL`** (RF12) |
| 8 | `market_category` | категория рынка для фильтров | **`NULL`** (RF12) |
| 9 | `open_trade_id` | ID первой BUY-сделки в позиции | `MIN(whale_trades.id)` группы |
| 10 | `open_side` | сторона открытия позиции | literal `'buy'` |
| 11 | `open_price` | средневзвешенная цена открытия | `SUM(price·size) / SUM(size)` |
| 12 | `open_size_usd` | суммарный размер позиции в USD | `SUM(whale_trades.size_usd)` группы |
| 13 | `opened_at` | время первой BUY-сделки позиции | `MIN(whale_trades.traded_at)` |
| 14 | `close_trade_id` | ID сделки закрытия (на 3A пусто) | `NULL` |
| 15 | `close_side` | сторона закрытия позиции | `NULL` |
| 16 | `close_price` | цена закрытия позиции | `NULL` |
| 17 | `close_size_usd` | размер закрытия позиции USD | `NULL` |
| 18 | `closed_at` | время закрытия позиции | `NULL` |
| 19 | `close_type` | тип закрытия позиции SELL/SETTLEMENT | `NULL` |
| 20 | `status` | текущее состояние roundtrip-а | literal `'OPEN'` |
| 21 | `gross_pnl_usd` | валовый P&L закрытой позиции | `NULL` |
| 22 | `fees_usd` | суммарные комиссии позиции | `0` (literal) |
| 23 | `net_pnl_usd` | чистый P&L после комиссий | `NULL` |
| 24 | `pnl_status` | статус доступности P&L данных | literal `'UNAVAILABLE'` |
| 25 | `matching_method` | метод матчинга закрытия EXACT/FLIP | `NULL` |
| 26 | `matching_confidence` | уверенность матчинга закрытия | `NULL` |
| 27 | `created_at` / `updated_at` | служебные timestamp-ы записи | `NOW()` в SQL |

### 9.4 Сценарий UPDATE для существующего position_key

Не применяется. `ON CONFLICT (position_key) DO NOTHING` — никакого UPDATE на стадии 3A не происходит. При наличии записи (любого status) новый INSERT молча отбрасывается; счётчик `len(roundtrips)` врёт о фактически вставленных (RF1, RF3).

Поля `whale_id`, `market_title`, `market_category` могут обновляться downstream-процессами (cron `category_backfill.py`, шаг 4 `update_whale_pnl_from_roundtrips`), но не шагом 3A.

---

## 10. Условия успеха / частичного успеха / неуспеха

| Исход | Условие | Возврат `_save_roundtrips` | Последствия |
|-------|---------|----------------------------|-------------|
| Полный успех | Все INSERT прошли | `len(roundtrips)` | Все новые позиции в БД |
| Silent skip части | Часть position_key уже существует | `len(roundtrips)` (врёт, RF3) | Существующие записи не обновлены, новые добавлены |
| Падение середины | Любой `execute` бросил исключение | exception пробрасывается | Вся транзакция откатывается (commit ещё не дошёл); следующий цикл через 2h начнёт всё заново (RF9) |
| Пустой ввод | `roundtrips = []` (нет BUY групп) | `saved = 0` (без вызова `_save_roundtrips`) | NoOp, heartbeat записан |

---

## 11. Зависимости

### Upstream

- **Шаг 2B** — `whale_trades` должна содержать BUY-события. Без записей с `side='buy'` шаг 3A выдаёт пустой результат.
- **Шаг 2A** — `whales` должна содержать кита для корректного JOIN. При отсутствии записи в `whales` (RF#1 шага 2B) — `whale_id` в roundtrip будет `NULL` (RF8).

### Downstream

- **Шаг 3B** (settlement, ACTIVE) — читает `whale_trade_roundtrips WHERE status='OPEN'` и UPDATE-ит до `CLOSED` через резолюцию рынка.
- **Шаг 3C** (SELL-close, DORMANT) — в текущей топологии не запускается; при ре-активации читал бы те же OPEN-roundtrip-ы.
- **`update_whale_pnl_from_roundtrips`** (шаг 4) — агрегирует закрытые roundtrip-ы в `whales` (P&L, WR).
- **Cron `category_backfill.py`** — дозаполняет `market_title`, `market_category` в `whale_trade_roundtrips` (RF12 mitigation).

### External

Никаких external API (HTTP, gRPC) шаг 3A не использует. Только PostgreSQL на `postgres:5432` через `DATABASE_URL`.

---

## 12. Наблюдаемость

### Логи

`logger = print` (`roundtrip_builder.py:38`) — все логи через `print()`, без структурированного формата и без уровней. Контейнерный stdout захватывается docker-логером (`json-file`, max-size 50m, max-file 3).

Ключевые сообщения за итерацию `run()`:
- `ROUNDTRIP BUILDER (ARC-502-A) - Starting` (`:951`)
- `[1/4] Found N unique position groups` (`:957`)
- `[2/4] Found M existing OPEN roundtrips` (`:967`)
- `[3/4] Will create: K` (`:972`)
- `[4/4] Saved S records` (`:978`)
- `Database stats: {...}` (`:992`)
- `ROUNDTRIP BUILDER (ARC-502-A) - Complete` (`:987`)

Различие WARN/ERROR/INFO — отсутствует. Алертинг по логам затруднён (RF6).

### Метрики

Не экспортируются. Prometheus/Statsd-эндпоинтов нет.

### Heartbeat

`/tmp/heartbeat` — записывается datetime ISO-форматом в конце каждого `run()` (`:996–1001`). Healthcheck docker-compose проверяет возраст файла ≤10 минут. При sleep=7200s healthcheck **гарантированно** проходит между итерациями (heartbeat обновляется чаще, чем за 10 минут от предыдущего), пока сам `run()` не зависает.

### Что наблюдатель НЕ видит

- Различие «новая позиция добавлена» vs «position_key уже существовал и был skipped» — оба исхода скрыты под общим counter `Saved S records`.
- Реальный rowcount INSERT — нигде не логируется (RF3).
- Деградацию SQL-производительности при росте `whale_trades` (RF5) — нужен внешний мониторинг postgres.

---

## 13. Особые случаи и риски (RED FLAGs)

**RF1 — `ON CONFLICT DO NOTHING` без различения status.**
`roundtrip_builder.py:262`. При существовании записи с тем же `position_key` (любой status — OPEN, CLOSED, PARTIAL и т.д.) новый INSERT молча отбрасывается. Следствие: повторное открытие позиции (re-open после закрытия) физически невозможно — `UNIQUE (position_key)` блокирует. Это известно как ARCH-001 в BUG-608 и является P0-блокером всей whale-аналитики проекта; в скоупе шага 3A фиксируется как ограничение поведения INSERT.

**RF2 — `existing_keys` вычисляется, но не используется.**
`roundtrip_builder.py:965–967`. В блоке [2/4] вызывается `_get_existing_open_position_keys()`, результат логируется как diagnostic. В `_create_roundtrips` фильтрация по `existing_keys` НЕ выполняется — защита от создания дубликатов лежит исключительно на `ON CONFLICT`. При снятии constraint `UNIQUE(position_key)` (рассматривалось в плане ARC-608) поведение станет undefined.

**RF3 — возвращаемый счётчик не равен фактическому rowcount.**
`roundtrip_builder.py:270`. `_save_roundtrips` возвращает `len(roundtrips)` (число переданных dict-ов), не результат `cursor.rowcount`. При срабатывании `ON CONFLICT DO NOTHING` для части записей лог `[4/4] Saved S records` врёт. Метрика «сколько реально новых позиций добавлено» — недоступна без прямого SELECT-а к БД.

**RF4 — FK `paper_trade_id → trades(trade_id)`, не `paper_trades`.**
`migration_whale_trade_roundtrips.sql:81`. Поле `paper_trade_id` ссылается на DEPRECATED-таблицу `trades` (PROJECT_STATE: содержит только тестовые данные). По INDEX и context transfer ожидалась связь с `paper_trades`. Шаг 3A это поле НЕ заполняет (всегда NULL в INSERT — отсутствует в списке колонок). Кто именно UPDATE-ит `paper_trade_id` — за пределами скоупа 3A, фиксируется как cross-step open question.

**RF5 — SQL без временного фильтра, полный скан каждые 2h.**
`roundtrip_builder.py:98–115`. Запрос `_fetch_and_group_buy_trades` не ограничен по `traded_at`. На корпусе 163k+ BUY-событий это уже работает медленнее, чем при старте проекта; при дальнейшем росте — деградация. Возможное решение (incremental через cursor по `whale_trades.id` или `traded_at`) — не реализовано; не блокирует функциональность, но создаёт technical debt.

**RF6 — `logger = print`.**
`roundtrip_builder.py:38`. Все логи — обычные `print()` без уровней (INFO/WARNING/ERROR) и без структуры (нет JSON, нет timestamp в каждой строке). Алертинг «упал _fetch_and_group_buy_trades» или «выросло число skipped via ON CONFLICT» — невозможен без переработки логирования.

**RF7 — `whale_roundtrip_reconstructor.py` — dead duplicate с другой формулой position_key.**
Файл существует (`src/strategy/whale_roundtrip_reconstructor.py`); caller в `main.py:359` закомментирован per `SYS-601-FIX`. Использует формулу `sha256(wallet:market:outcome:open_trade_id)[:32]` — несовместимую с `roundtrip_builder.py` (plain string `{wallet}:{market}:{outcome}`). Содержит `ON CONFLICT (position_key) DO UPDATE SET` (не DO NOTHING). Риск: при ре-активации без снятия `UNIQUE(position_key)` две формулы создадут конфликт записей; ARC-608 план предполагал удаление файла, но заморожен.

**RF8 — LEFT JOIN сохраняет `whale_id IS NULL`.**
`roundtrip_builder.py:108`. Сделки от китов, не зарегистрированных в `whales` (RF#1 шага 2B — wallets с <10 сделок, либо сбои `_lookup_whale_id`), попадают в группировку с `w.id = NULL`. Roundtrip создаётся с `whale_id IS NULL`. **На стороне 3A это закрывает RF#1 шага 2B**: BUY-сделки без `whale_id` не теряются. Открытый вопрос для шага 4: как `update_whale_pnl_from_roundtrips` обрабатывает roundtrip-ы с `whale_id IS NULL` (вероятно — игнорирует, агрегаты `whales` остаются неполными).

**RF9 — Atomic batch commit без savepoint.**
`roundtrip_builder.py:265–268`. Цикл `for rt in roundtrips: conn.execute(query, rt)` + один `conn.commit()` после цикла. При ошибке `execute` в середине партии вся транзакция откатывается, прогресс итерации теряется; следующий запуск через 2 часа начнёт всё заново. Для NULL-конфликтов и `ON CONFLICT` это безопасно (constraint обрабатывается через `DO NOTHING`); опасно для transient FK-violation, deadlock, connection drop в середине цикла.

**RF10 — Latent: BACKFILL-путь пишет `outcome IS NULL`.**
`whale_detector.py:545` — вызов `save_trade_to_db` в `_process_trade()` НЕ передаёт `outcome` (по умолчанию `None`). Гипотетически BUY-сделка такого происхождения попала бы в группу с `wt.outcome IS NULL`; position_key получил бы literal `'unknown'`. На корпусе 2026-05 не наблюдается: `SELECT outcome WHERE outcome IS NULL OR outcome = '' OR outcome = 'unknown'` возвращает пустой результат. Открытый вопрос: при каких условиях `_process_trade` вообще выполняется — поведение DORMANT или REACHABLE — не определено в скоупе 3A.

**RF11 — Latent: коллизия NULL group ↔ literal `'unknown'` в position_key.**
SQL `GROUP BY wt.outcome` группирует все NULL-строки в одну группу. Python-генератор position_key превращает `None` в `'unknown'`. Если бы в `whale_trades.outcome` существовала строка-значение `'unknown'`, обе категории дали бы одинаковый `position_key`. На корпусе 2026-05 не наблюдается. Latent risk при изменении upstream-нормализации.

**RF12 — `market_title` и `market_category` всегда NULL после 3A.**
`roundtrip_builder.py:137`, `:184`. SQL `_fetch_and_group_buy_trades` не выбирает `market_title`; `_create_roundtrips` присваивает `'market_title': None`, `'market_category': None`. Backfill выполняется cron-скриптом `category_backfill.py` (раз в 2 часа) — не синхронно с созданием roundtrip-а. Downstream-логика, фильтрующая по категории в окне <2h, может видеть NULL.

**Factual observation (не RF, наблюдение):** в production-данных существуют киты, открывающие до 4 разных позиций по разным `outcome` одного `market_id` (выборки `{Yes, No, Cavaliers, Hawks}`, `{Yes, No, Daniel Altmaier, Hamad Medjedovic}`). Каждый outcome → отдельный position_key → отдельный roundtrip. Downstream-логика, считающая P&L по `market_id` без учёта `outcome`, агрегирует независимые позиции как одну.

---

## 14. Результат шага

После успешного выполнения одной итерации `run(rebuild=False)`:

- В `whale_trade_roundtrips` для каждой новой тройки `(wallet, market, outcome)` (которая ещё не существовала в таблице в любом status) создана строка со `status='OPEN'`, заполненными open-полями (см. §9.3) и NULL close-полями.
- Существующие записи (любого status) не модифицированы — `ON CONFLICT DO NOTHING`.
- `created_at` и `updated_at` = время INSERT, не время первой покупки кита.
- `market_title` и `market_category` в записи = NULL до фонового backfill.
- Heartbeat-файл `/tmp/heartbeat` обновлён.

**Состояние сделок в магистрали:** BUY-сделки кита по каждой тройке `(wallet, market, outcome)` агрегированы в одну OPEN-позицию. Сами строки `whale_trades` не модифицированы (3A — read-only по отношению к `whale_trades`). С этого момента позиция кита представлена в системе двумя «слоями»:
- Сырые события в `whale_trades` (per-trade, неизменно с момента 2B).
- Агрегированная открытая позиция в `whale_trade_roundtrips` (per-position, может быть закрыта downstream).

**Связь со следующим шагом магистрали:**

OPEN-roundtrip остаётся в состоянии `OPEN` до закрытия. Закрытие выполняется двумя независимыми параллельными шагами магистрали:

- **Шаг 3B** (settlement, ACTIVE) — cron `run_settlement.sh` каждые 2 часа JOIN-ит OPEN-roundtrip-ы с `market_resolutions` и UPDATE-ит до `close_type='SETTLEMENT_WIN'/'SETTLEMENT_LOSS'`.
- **Шаг 3C** (SELL, DORMANT в auto-pipeline) — метод `_close_roundtrips()` существует в `roundtrip_builder.py`, но в production не вызывается (флаг `--close` не используется ни одним cron / supervisor / docker).

Магистраль продолжается по тому пути, который сработает раньше. В текущей топологии **доминирует шаг 3B**: по корпусу 2026-05-08 — 42301 closed roundtrip через settlement vs 530 через SELL (1.2% от закрытых). Из 14564 SELL-событий в `whale_trades` в roundtrip-ы превратилось <4% (см. сводку BUG-608).

---

## 15. Краткая бизнес-формула шага

```
ВХОД: контейнер roundtrip_builder, итерация цикла while-true
      (sleep 7200, без CLI-флагов)
  │
  ├── builder.run(rebuild=False)
  │
  ├── [1/4] _fetch_and_group_buy_trades()
  │     SELECT ... FROM whale_trades
  │     LEFT JOIN whales (whale_id может быть NULL — RF8)
  │     WHERE side='buy'  (SELL игнорируется на 3A)
  │     GROUP BY wallet, market, outcome, whale_id
  │     ── Полный скан без временного фильтра (RF5)
  │     ── Возвращает Dict[position_key → trade_data]
  │
  ├── [2/4] _get_existing_open_position_keys()   ← diagnostic only
  │     Результат логируется, в фильтрации НЕ участвует (RF2)
  │
  ├── [3/4] _create_roundtrips(grouped_trades)
  │     Для каждой группы → dict из 27 полей:
  │       - open-поля заполнены из SQL aggregate
  │       - close-поля = NULL
  │       - market_title, market_category = NULL (RF12)
  │       - status = 'OPEN', pnl_status = 'UNAVAILABLE'
  │       - id = uuid4()
  │
  ├── [4/4] _save_roundtrips(roundtrips)
  │     for rt in roundtrips:
  │         conn.execute(INSERT ... ON CONFLICT (position_key) DO NOTHING)
  │     conn.commit()  ← один commit на партию (RF9)
  │     return len(roundtrips)  ← врёт при ON CONFLICT (RF3)
  │
  ├── _get_statistics() + heartbeat write
  │
  └── sleep 7200 → следующая итерация

При ошибке execute в середине → rollback всей партии,
следующий запуск через 2 часа начнёт всё заново (RF9).

Закрытие позиции (status OPEN → CLOSED) — НЕ в скоупе 3A:
  - Шаг 3B: settlement через cron run_settlement.sh
  - Шаг 3C: SELL-close, DORMANT в auto-pipeline
```