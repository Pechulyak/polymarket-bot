# ШАГ 2B. ЗАПИСЬ СДЕЛКИ В ТАБЛИЦУ `whale_trades`

## Краткая характеристика (TL;DR)

Шаг 2 — точка ветвления магистрали на две независимые параллельные ветви:
- **Шаг 2A** — регистрация / обновление **кита** в таблице `whales` (per-address). Описан отдельным документом.
- **Шаг 2B** — запись **сделки** в таблице `whale_trades` (per-trade). Этот документ.

### Шаг 2B в бизнес-нотации

Каждый раз, когда система получает свежие сделки китов из Polymarket Data API (шаг 1), она проходит по списку сделка-за-сделкой и для каждой выполняет короткую последовательность: проверяет корректность данных (`side`, `size_usd`, `price`), нормализует поля (адрес кита в lower-case, время сделки, категория рынка), находит ID кита в каталоге `whales`, проверяет, не записывалась ли эта сделка раньше (по `tx_hash`), и при отсутствии дубликата вставляет новую строку в `whale_trades`. Если кит ещё не зарегистрирован в каталоге `whales` (только что обнаружен), сделка всё равно записывается, но **со связкой `whale_id = NULL`** — связь с китом установится позже (через `wallet_address`).

Шаг 2B выполняется во **всех 5 циклах** контейнера `whale-detector`: discovery (60s), paper (30s), tracked (300s), HOT (4h), WARM (24h). Все циклы сходятся в **единую точку записи** — `WhaleTradesRepo.save_trade()` (`whale_trades_repo.py:37`).

---

## 1. Назначение шага

Шаг обеспечивает **persistence сделок китов** в БД. Без этого шага сырьё, полученное на шаге 1, теряется при следующей итерации цикла. Только записанные в `whale_trades` сделки доступны для downstream-процессов: реконструкции roundtrips, copy-trading (через DB-trigger), P&L-аналитики, отчётов и алертов.

Бизнес-смысл: «получили сделку → проверили валидность → записали в каталог сделок».

---

## 2. Статус

**CONFIRMED-ACTIVE** для всех 5 циклов записи:
- `WhaleDetector._polymarket_poll_loop` (discovery, 60s) → `save_trade_to_db` (`whale_detector.py:1237`) → `WhaleTradesRepo.save_trade()`
- `WhaleDetector._paper_poll_loop` (paper, 30s) → `save_trade_to_db` → `save_trade()`
- `WhaleDetector._tracked_poll_loop` (tracked, 300s) → `save_trade_to_db` → `save_trade()`
- `WhalePoller.run_hot_polling` (HOT, 4h) → `_save_whale_trade` (`whale_poller.py:294`) → `save_trade()`
- `WhalePoller.run_warm_polling` (WARM, 24h) → `_save_whale_trade` → `save_trade()`

Дата верификации: 2026-05-11.

---

## 3. Исходные файлы

**Точка записи (Repo):**
`src/db/whale_trades_repo.py` — класс `WhaleTradesRepo`, метод `save_trade()` (`whale_trades_repo.py:37–209`) и приватный `_lookup_whale_id()` (`whale_trades_repo.py:211–227`).

**Обёртки (две независимые):**
- `WhaleDetector.save_trade_to_db()` (`whale_detector.py:1237–1250`) — единая обёртка для 3 циклов discovery / paper / tracked. Возвращает `True` если результат `save_trade()` == `"saved"`, иначе `False`.
- `WhalePoller._save_whale_trade()` (`whale_poller.py:294`) — обёртка для циклов HOT / WARM.

**Конструкторы значений (вне Repo):**
- `polymarket_data_client.py:199–244` — парсинг ответа API в `TradeWithAddress` (поля, маппинг, преобразования)
- `market_category_cache.py` — обогащение `market_category` только в WhalePoller (`whale_poller.py:290–291`)

**Источник `whale_id` (FK lookup):**
Таблица `whales`, заполняемая шагом 2A. См. сценарий «кит не зарегистрирован» в §6 и RED FLAG #1 в §13.

---

## 4. Контейнер

`whale-detector` — отдельный docker-compose сервис.
Команда запуска: `python src/run_whale_detection.py`.
Шаг 2B выполняется внутри того же процесса, что и шаги 1 и 2A. Никаких внешних сервисов или отдельных воркеров не используется.

---

## 5. Триггер запуска и расписание

Шаг 2B запускается **5 циклами** контейнера `whale-detector`:

| Цикл | Интервал | Обёртка | Source-классификация |
|------|----------|---------|----------------------|
| `_polymarket_poll_loop` (discovery) | 60s | `save_trade_to_db` | `"BACKFILL"` |
| `_paper_poll_loop` | 30s | `save_trade_to_db` | `"PAPER_TRACK"` |
| `_tracked_poll_loop` | 300s | `save_trade_to_db` | `"TRACKED"` |
| `WhalePoller.run_hot_polling` | 4h | `_save_whale_trade` | `"POLLER"` |
| `WhalePoller.run_warm_polling` | 24h | `_save_whale_trade` | `"POLLER"` |

**Соотношение с шагом 2A:**
- В discovery-цикле шаг 2B выполняется **до** шага 2A в рамках одной итерации `_fetch_polymarket_whales()`: сначала пер-сделочный цикл (`whale_detector.py:1462–1489`), затем пер-адресный (`whale_detector.py:1501–1620`). Для впервые встреченного кита это создаёт окно, в котором `_lookup_whale_id()` возвращает `None` — см. §6 и RED FLAG #1 в §13.
- В остальных 4 циклах шаг 2A **не выполняется** вообще; они работают с уже зарегистрированными китами, выбранными из `whales` по `copy_status` или `tier`.

---

## 6. Алгоритм шага

### 6.1 Точка входа

Каждый цикл, обработав свой источник сделок (`fetch_recent_trades` или `fetch_trader_trades`), вызывает обёртку, которая передаёт параметры в `WhaleTradesRepo.save_trade()` (`whale_trades_repo.py:37`).

### 6.2 Тело `save_trade()` — 13 логических блоков

Последовательность блоков в порядке выполнения (по отчёту STEP-2B-REPO-INTERNALS, раздел 2):

1. **Валидация `side`** (`whale_trades_repo.py:60–70`)
   - Проверка `side IN ("buy", "sell")` после нормализации `.lower().strip()`
   - При несоответствии: `return "rejected"`, лог WARNING, сделка теряется

2. **Валидация `size_usd`** (`whale_trades_repo.py:72–82`)
   - Проверка `size_usd > 0`
   - При несоответствии: `return "rejected"`, лог WARNING

3. **Валидация `price`** (`whale_trades_repo.py:84–94`)
   - Проверка `price > 0`
   - При несоответствии: `return "rejected"`, лог WARNING

4. **Нормализация `market_category`** (`whale_trades_repo.py:96–107`)
   - Если `None` или пустая строка → подставляется `"unknown"`
   - Инкрементируется внутренний счётчик пропусков (для метрик)
   - **НЕ отклоняет** запись

5. **Предупреждение при missing `outcome`** (`whale_trades_repo.py:109–115`)
   - Если `outcome` пуст: лог WARNING, но запись не отклоняется
   - В БД `outcome` пишется как есть (может быть `None`)

6. **Нормализация `wallet_address`** (`whale_trades_repo.py:119–120`)
   - `.lower().strip()` — приведение к каноническому виду для FK lookup и dedup

7. **Нормализация `traded_at`** (`whale_trades_repo.py:122–124`)
   - Если `None` → подставляется `datetime.utcnow()`
   - **RED FLAG #6 в §13:** `utcnow()`, а не время сделки из API. Для сделок, у которых `traded_at` не передан обёрткой, в БД попадает время вызова `save_trade()`, не реальное время сделки

8. **Lookup `whale_id`** (`whale_trades_repo.py:126–127`)
   - Вызов `_lookup_whale_id(wallet_address)` (см. §6.3)
   - Возвращает `int` или `None`
   - `None` **не блокирует** запись — идёт в INSERT как есть

9. **Gate дедупликации по `tx_hash`** (`whale_trades_repo.py:134–148`)
   - Условие: `if tx_hash and tx_hash.strip():`
   - Если **истинно**: выполняется `SELECT 1 FROM whale_trades WHERE tx_hash = :tx_hash`. При попадании → `return "duplicate"`, лог DEBUG, инкремент счётчика `duplicates`.
   - Если **ложно** (`None` или `""`): блок целиком пропускается, дедупликация **не выполняется** для этой записи
   - **RED FLAG #3 в §13:** дедупликация двухфазная (SELECT-then-INSERT), не атомарная — TOCTOU-окно между блоками 9 и 10.

10. **INSERT в `whale_trades`** (`whale_trades_repo.py:150–177`)
    - SQL: `INSERT INTO whale_trades (12 колонок) VALUES (:placeholders)` — точные строки `:151–162`
    - Словарь параметров — строки `:163–176`, 12 ключей (полный список в §9)
    - Никаких `RETURNING`, `ON CONFLICT` — чистый INSERT

11. **Commit и возврат `"saved"`** (`whale_trades_repo.py:178–188`)
    - `session.commit()`, инкремент счётчика `saved`, лог DEBUG, `return "saved"`

12. **Обработка `SQLAlchemyError`** (`whale_trades_repo.py:189–197`)
    - `session.rollback()`, лог ERROR, `raise` — исключение **пробрасывается наружу**, обёртка должна его поймать

13. **Обработка прочих исключений** (`whale_trades_repo.py:202–209`)
    - Лог ERROR, `raise` — пробрасывается наружу

### 6.3 `_lookup_whale_id()` — поиск `whale_id` в каталоге

Метод `whale_trades_repo.py:211–227`:

```
SELECT id FROM whales WHERE wallet_address = :wallet
```

Параметр `wallet` — `wallet_address.lower().strip()` (внутренняя нормализация).

**Возвращает:**
- `int` — `id` кита, если строка найдена в `whales`
- `None` — если строка не найдена
- `None` — если возникла `SQLAlchemyError` (например, БД недоступна)
- `None` — если возникло любое другое исключение

**RED FLAG #4 в §13:** молчаливое поглощение исключений — внешний наблюдатель не отличает «кит не существует» от «БД упала».

### 6.4 Поведение для впервые встреченного кита (закрытие RED FLAG #4 из шага 2A)

В discovery-цикле сделка нового кита проходит блок 8 (`_lookup_whale_id`) **до** того, как ветка 2A зарегистрирует этого кита в `whales`. Результат: `whale_id = None` попадает в INSERT, запись создаётся со связкой `whale_id = NULL`.

В следующей итерации (через 60 секунд) тот же кит уже зарегистрирован, и его новые сделки получают корректный `whale_id`. Однако **первые сделки навсегда остаются с `whale_id = NULL`** на уровне таблицы — никакой автоматический backfill в коде `save_trade()` не предусмотрен. RED FLAG #1 в §13.

### 6.5 Точки ветвления магистрали внутри шага 2B

```
                  ВХОД: вызов save_trade(...)
                          │
              ┌───────────┼───────────┬───────────┐
        Gate 1 side    Gate 2 size  Gate 3 price  pass-through
        не buy/sell    ≤ 0          ≤ 0
              │           │            │            │
              ▼           ▼            ▼            ▼
            "rejected" — сделка отбрасывается, наружу логи WARNING

                                                   │ (прошли валидации)
                                                   ▼
                                          нормализация полей
                                                   │
                                                   ▼
                                          lookup whale_id
                                                   │
                                                   ├── найден → int
                                                   └── не найден → None
                                                   │
                                                   ▼
                                          tx_hash непустой?
                                                   │
                                          ┌────────┴────────┐
                                         ДА                 НЕТ
                                          │                  │
                                          ▼                  │
                                   SELECT по tx_hash         │
                                          │                  │
                                  ┌───────┴──────┐           │
                              существует     отсутствует     │
                                  │              │           │
                                  ▼              ▼           ▼
                              "duplicate"    INSERT       INSERT
                                                │           │
                                                ▼           ▼
                                            "saved"     "saved"
                                                          (tx_hash = NULL)
```

---

## 7. Формат входных данных

`save_trade()` принимает 12 параметров:

| Параметр | Тип | Default | Источник |
|----------|-----|---------|----------|
| `wallet_address` | `str` | — | `trade.trader` из API, lower-case |
| `market_id` | `str` | — | `trade.condition_id` |
| `side` | `str` | — | `"buy"` / `"sell"` после нормализации |
| `size_usd` | `Decimal` | — | `size_shares * price` (discovery/paper/tracked) или `trade.size_usd` (HOT/WARM) |
| `price` | `Decimal` | — | `trade.price` |
| `outcome` | `Optional[str]` | `None` | результат `normalize_outcome()` |
| `market_title` | `Optional[str]` | `None` | `trade.market_title` из API |
| `market_category` | `Optional[str]` | `None` | None для discovery/paper/tracked; `get_market_category(condition_id)` для HOT/WARM |
| `tx_hash` | `Optional[str]` | `None` | `trade.tx_hash`; **не передаётся в HOT/WARM** — RED FLAG #2 в §13 |
| `source` | `str` | `"BACKFILL"` | hardcoded в обёртках: BACKFILL / PAPER_TRACK / TRACKED / POLLER |
| `traded_at` | `Optional[datetime]` | `None` | `datetime.fromtimestamp(trade.timestamp)` |

---

## 8. Формат выходных данных

`save_trade()` возвращает строку — одно из трёх значений:

| Значение | Условие | Файл:строка |
|----------|---------|-------------|
| `"rejected"` | `side` не `buy`/`sell` | `whale_trades_repo.py:70` |
| `"rejected"` | `size_usd <= 0` | `whale_trades_repo.py:82` |
| `"rejected"` | `price <= 0` | `whale_trades_repo.py:94` |
| `"duplicate"` | Найден существующий `tx_hash` в `whale_trades` | `whale_trades_repo.py:148` |
| `"saved"` | Успешный INSERT + commit | `whale_trades_repo.py:188` |

При исключении (`SQLAlchemyError` или прочее) метод **не возвращает значение**, а пробрасывает исключение наружу (`raise` на строках `:197` и `:209`).

**Использование возвращаемого значения вызывающим кодом:**
- `WhaleDetector.save_trade_to_db()` (`whale_detector.py:1250`): `return result == "saved"` — возвращает `True` только при успехе. Все остальные исходы (`"rejected"` / `"duplicate"`) сводятся к `False` без различия.
- `WhalePoller._save_whale_trade()` (`whale_poller.py:294`): из отчёта STEP-2-DISCOVERY известно, что не передаёт `tx_hash`; использование возвращаемого значения не зафиксировано в скоупе. Внешнее различие «rejected vs duplicate vs saved» теряется на уровне обёртки.

---

## 9. Записи в БД

**Таблица:** `whale_trades`
**Операция:** `INSERT INTO whale_trades (...) VALUES (:placeholders)`
**Файл SQL:** `whale_trades_repo.py:151–162`
**Файл параметров:** `whale_trades_repo.py:163–176` (12 ключей)
**Commit:** `whale_trades_repo.py:188`

### Полный список заполняемых столбцов (12 шт)

| Колонка | Бизнес-смысл | INSERT-only? | Источник значения | Файл:строка |
|---------|--------------|--------------|--------------------|-------------|
| `whale_id` | FK на каталог `whales`, может быть NULL | INSERT only | `_lookup_whale_id(wallet_address)`, может быть `None` | `whale_trades_repo.py:164` |
| `wallet_address` | адрес кошелька трейдера-кита | INSERT only | `wallet_address.lower().strip()` | `whale_trades_repo.py:165` |
| `market_id` | уникальный идентификатор рынка Polymarket | INSERT only | `trade.condition_id` из API | `whale_trades_repo.py:166` |
| `market_title` | человекочитаемое название рынка | INSERT only | `trade.market_title` из API | `whale_trades_repo.py:167` |
| `side` | направление сделки покупка/продажа | INSERT only | `side.lower().strip()` (после валидации) | `whale_trades_repo.py:168` |
| `size_usd` | объём сделки в долларах | INSERT only | `trade.size_usd` или вычислено | `whale_trades_repo.py:169` |
| `price` | цена контракта в момент сделки | INSERT only | `trade.price` из API | `whale_trades_repo.py:170` |
| `outcome` | сторона ставки (Yes/No) | INSERT only | `normalize_outcome(trade.outcome)` | `whale_trades_repo.py:171` |
| `market_category` | категория рынка для downstream-фильтрации | INSERT only | `market_category` или `"unknown"` fallback | `whale_trades_repo.py:172` |
| `traded_at` | момент совершения сделки | INSERT only | `datetime.fromtimestamp(trade.timestamp)` или `utcnow()` | `whale_trades_repo.py:173` |
| `tx_hash` | хеш транзакции для дедупликации | INSERT only | `tx_hash.strip()` или `None` | `whale_trades_repo.py:174` |
| `source` | источник записи в pipeline | INSERT only | hardcoded в обёртках (BACKFILL/PAPER_TRACK/TRACKED/POLLER) | `whale_trades_repo.py:175` |

### Сценарий «впервые встреченный кит»

В discovery-цикле для нового кита `_lookup_whale_id()` возвращает `None` → колонка `whale_id` записывается как **NULL**. Запись успешно создаётся (INSERT не имеет FK-enforcement в коде Repo; защита со стороны схемы — за рамками шага 2B, см. RED FLAG #1 в §13). Связка кита со сделкой устанавливается на уровне приложения через `wallet_address`, не через FK.

### Idempotency

**Условная.** Двухфазная дедупликация по `tx_hash`:
- При `tx_hash` непустом и уникальном: повторный вызов с теми же параметрами вернёт `"duplicate"` без повторной записи.
- При `tx_hash = None` или `""` (циклы HOT/WARM): дедупликация **не работает**, повторные вызовы создают дубликаты — RED FLAG #2 в §13.

### Constraints / FK / индексы

- Из кода Repo **не видно**: FK enforcement, NOT NULL constraints, UNIQUE на `tx_hash`. Все эти аспекты заданы на уровне схемы БД (`init_db.sql`) и за рамками этого шага.
- Что **точно известно** из кода: `whale_id = NULL` записывается без ошибки — значит либо FK отсутствует, либо настроен как nullable.

---

## 10. Условия успеха / частичного успеха / неуспеха

**Успех (одна сделка):** `save_trade()` возвращает `"saved"`. Строка в `whale_trades` создана. Обёртка получает `True` (для `save_trade_to_db`).

**Условный успех — дедупликация:** `save_trade()` возвращает `"duplicate"`. Строка **не создаётся**, но это считается штатным поведением — не ошибка. Счётчик дубликатов инкрементируется.

**Отказ валидации:** `save_trade()` возвращает `"rejected"`. Строка **не создаётся**, лог WARNING. Обёртка получает `False`. Внешний наблюдатель видит только `False` — не понимая, было ли это `"rejected"` или `"duplicate"`.

**Неуспех (исключение):**
- `SQLAlchemyError` (сбой БД, нарушение constraint, дисконнект): `session.rollback()`, лог ERROR, `raise`. Обёртка должна поймать.
- Прочее исключение: лог ERROR, `raise`.
- **В коде обёрток** (`WhaleDetector.save_trade_to_db`, `WhalePoller._save_whale_trade`) поведение при `raise` из Repo не зафиксировано в скоупе. По умолчанию исключение прервёт обработку текущей сделки, но не цикл (вышестоящие методы имеют `try/except` на уровне итерации — `whale_detector.py:1648`).

**Частичный успех на уровне итерации цикла:**
- Часть сделок записана, часть отвергнута, часть упала с исключением. Каждая обрабатывается независимо; ошибка одной не блокирует обработку следующей.

---

## 11. Зависимости

### Upstream

- **Шаг 1** — поставляет `List[TradeWithAddress]` через 5 циклов
- **Шаг 2A** (косвенно) — поставляет записи в `whales`, на которые ссылается `_lookup_whale_id`. Шаг 2B **не блокируется** отсутствием записи в `whales` — пишет `whale_id = NULL`, но качество связи зависит от шага 2A
- **Cache `market_category`** (только для HOT/WARM, `whale_poller.py:290–291`) — внешний lookup-сервис

### Downstream consumers таблицы `whale_trades`

| Консьюмер | Тип использования | Триггер |
|-----------|-------------------|---------|
| **DB-trigger `trigger_copy_whale_trade`** | AFTER INSERT, создаёт `paper_trades` для китов с `copy_status='paper'` | автоматически при каждом INSERT |
| `roundtrip_builder` | SELECT, реконструкция позиций → `whale_trade_roundtrips` | контейнерный while-loop, 2h |
| `category_backfill.py` | UPDATE, дозаполнение `market_category` для записей с `"unknown"` | cron, каждые 2 часа |
| materialized view `whale_pnl_summary` | SELECT агрегаций | refresh 2h |
| materialized view `paper_simulation_pnl` | SELECT по сделкам paper-китов | refresh 2h |

**Самый критичный downstream** — DB-trigger, который превращает шаг 2B в точку запуска **следующего шага магистрали** (создание paper-сделки). Это первый кандидат на шаг 3.

### External services

Нет на уровне Repo. Cache `market_category` внешний только для HOT/WARM, и используется **до** вызова `save_trade()`.

### Параллельная ветвь (не зависимость, а параллелизм)

- **Шаг 2A** выполняется в той же итерации `_fetch_polymarket_whales()` (discovery-цикл), но **после** шага 2B. Это создаёт временное окно, в котором `whale_id = NULL` для впервые встреченных китов. См. RED FLAG #1 в §13.

---

## 12. Наблюдаемость

### Логи

| Событие | Уровень | Контекст | Файл:строка |
|---------|---------|----------|-------------|
| `trade_rejected_invalid_side` | WARNING | side, wallet_address[:10] | `whale_trades_repo.py:65–68` |
| `trade_rejected_invalid_size` | WARNING | size_usd, wallet_address[:10] | `whale_trades_repo.py:77–80` |
| `trade_rejected_invalid_price` | WARNING | price, wallet_address[:10] | `whale_trades_repo.py:89–92` |
| `trade_missing_category_fallback_unknown` | DEBUG/WARN | market_id[:20] | `whale_trades_repo.py:100–106` |
| `trade_missing_outcome` | WARNING | market_id[:20] | `whale_trades_repo.py:111–114` |
| `trade_duplicate` | DEBUG | tx_hash, wallet_address[:10] | `whale_trades_repo.py:142–146` |
| `trade_saved` | DEBUG | wallet_address[:10], side, size_usd | `whale_trades_repo.py:183–186` |
| `save_trade_db_error` | ERROR | error, wallet_address[:10] | `whale_trades_repo.py:192–195` |
| `save_trade_unexpected_error` | ERROR | error, wallet_address[:10] | `whale_trades_repo.py:204–207` |

### Метрики

Внутренние счётчики в Repo: `saved`, `duplicates`, `rejected`, `missing_category`. Эти счётчики **в коде Repo** инкрементируются, но экспорт в Prometheus / Statsd не верифицирован в текущем скоупе. RED FLAG #7 в §13.

### Алерты

Алертов конкретно на состояние шага 2B не обнаружено. `pipeline_monitor` (cron каждые 30 минут, по PROJECT_STATE) контролирует общее состояние pipeline через косвенные индикаторы (количество новых записей в `whale_trades` за окно). Точка отказа «дедупликация перестала срабатывать» или «`whale_id = NULL` массово растёт» — без алертов.

### Что наблюдатель НЕ видит

- Различие `"rejected"` vs `"duplicate"` на уровне обёртки `save_trade_to_db` — оба превращаются в `False`.
- Молчаливые `whale_id = NULL`: лог INFO/DEBUG не отмечает факт. Нужен прямой SQL-запрос к БД для обнаружения.
- Поглощённые исключения в `_lookup_whale_id` (SQLAlchemyError возвращает `None` без отдельного лога). RED FLAG #4.

---

## 13. Особые случаи и риски (RED FLAGs)

**RED FLAG #1 — Сделки с `whale_id = NULL`.**
Сценарий (b) из отчёта STEP-2B-REPO-INTERNALS: при `_lookup_whale_id()` → `None` запись производится с `whale_id = NULL`. Три источника таких записей:
- **Впервые встреченные киты в discovery-цикле** (за 1 итерацию, в следующей кит уже будет в `whales`). Узкое окно, но повторно.
- **Трейдеры с `< min_trades_for_quality = 10` сделок в текущем окне** (RED FLAG #4 шага 2A): шаг 2A их не регистрирует. Эти сделки **навсегда** остаются с `whale_id = NULL`.
- **Сбои `_lookup_whale_id`** (SQLAlchemyError, прочие исключения): молчаливый `return None` (`whale_trades_repo.py:222–227`).
Никакого backfill `whale_id` в коде `save_trade()` нет. Связь устанавливается на уровне приложения через JOIN по `wallet_address`, но downstream-процессы могут полагаться на `whale_id` напрямую — поведение для NULL-записей не верифицировано в скоупе.

**RED FLAG #2 — Дедупликация не работает в HOT/WARM-циклах.**
`WhalePoller._save_whale_trade()` (`whale_poller.py:294`) не передаёт `tx_hash` в `save_trade()`. Из отчёта STEP-2B-REPO-INTERNALS (раздел 4): при `tx_hash = None` блок дедупликации (`whale_trades_repo.py:134–148`) пропускается, запись идёт прямо в INSERT с `tx_hash = NULL`. Следствие: при повторном poll'инге HOT/WARM-кита одна и та же сделка может быть записана несколько раз. Защита со стороны UNIQUE constraint на `tx_hash` в БД — за рамками шага 2B, требует отдельной верификации (`init_db.sql`).

**RED FLAG #3 — Двухфазная дедупликация (TOCTOU-окно).**
Между блоком 9 (SELECT по `tx_hash`, `whale_trades_repo.py:137`) и блоком 10 (INSERT, `whale_trades_repo.py:151`) есть временной промежуток. Если два процесса/корутины одновременно вставляют сделку с одним `tx_hash`, оба пройдут SELECT, оба попытаются INSERT, и оба создадут дубликат — если на стороне БД нет UNIQUE constraint, защиты нет вообще. На текущем количестве процессов (1 контейнер `whale-detector`) риск ограничен, при горизонтальном масштабировании становится критичным.

**RED FLAG #4 — Молчаливое поглощение исключений в `_lookup_whale_id`.**
`whale_trades_repo.py:222–227`: и `SQLAlchemyError`, и `Exception` ловятся, возвращается `None` без лога. Внешний наблюдатель не отличает «кит не существует» (валидное состояние) от «БД упала» (инцидент). При деградации БД ВСЕ сделки начнут писаться с `whale_id = NULL`, и это не алертится.

**RED FLAG #5 — `market_category = "unknown"` для 3 из 5 циклов.**
Циклы discovery / paper / tracked передают `market_category = None` (`whale_detector.py:1245` и обёртка `save_trade_to_db`). На уровне Repo `None` → `"unknown"` (`whale_trades_repo.py:96–107`). Только HOT/WARM используют cache (`market_category_cache`). Следствие: в `whale_trades` для большинства записей `market_category = "unknown"` до тех пор, пока фоновая задача `category_backfill.py` (cron 2h) не дозаполнит. Downstream-логика, фильтрующая по категории в окне < 2 часов, будет видеть искажённую картину.

**RED FLAG #6 — `traded_at` fallback на `utcnow()` теряет реальное время сделки.**
`whale_trades_repo.py:122–124`: если обёртка не передала `traded_at`, подставляется `datetime.utcnow()` — момент записи в БД, не момент сделки. Все 3 обёртки WhaleDetector передают `datetime.fromtimestamp(trade.timestamp)`, WhalePoller также (`whale_poller.py:284`). Но если по какой-то причине обёртка передаст `None` (например, в будущем рефакторинге или при пустом timestamp от API), время сделки потеряется без явного индикатора. Защиты на уровне Repo (например, `raise ValueError`) нет.

**RED FLAG #7 — Внутренние счётчики Repo не экспортируются.**
В коде Repo инкрементируются `self._stats["saved"]`, `self._stats["duplicates"]`, `self._stats["rejected"]`, `self._stats["missing_category"]`. Эти счётчики — in-memory на инстансе `WhaleTradesRepo`, не экспортируются в Prometheus, не публикуются через HTTP endpoint, не сбрасываются по расписанию. Полезны только для отладочных дампов через debug-print или REPL. Алертинг «дедупликация выросла в 10 раз» — невозможен без переработки.

**RED FLAG #8 — Source-классификация хрупкая.**
Source (`BACKFILL` / `PAPER_TRACK` / `TRACKED` / `POLLER`) определяется hardcoded строкой в обёртке. На уровне Repo source принимает любое значение `str` без валидации против enum или списка. При опечатке (`"POLER"` вместо `"POLLER"`) запись пройдёт; downstream-фильтры по source молча перестанут её видеть. Унификация и валидация source — на ответственности обёрток, не централизована.

**RED FLAG #9 — Обёртка `save_trade_to_db` теряет различие `rejected` vs `duplicate`.**
`whale_detector.py:1250`: `return result == "saved"`. Все три исхода `save_trade()` сводятся к `True`/`False`. Вызывающий код в 3 циклах (`whale_detector.py:1462–1489`, `:1739–...`, `:1873–...`) на основе `False` не может сказать, отвергнута сделка из-за плохих данных (`rejected`) или это повторная запись (`duplicate`). Метрики «качество API данных» и «эффективность дедупликации» не разделимы на уровне обёртки.

---

## 14. Результат шага

После успешного выполнения для одной сделки:

- В таблице `whale_trades` существует новая строка с 12 заполненными колонками (см. §9).
- `whale_id` либо ссылается на корректную запись в `whales`, либо равен `NULL` (см. RED FLAG #1).
- `tx_hash` либо содержит уникальный хеш транзакции, либо равен `NULL` (для HOT/WARM или при отсутствии в API).
- `market_category` либо валиден (HOT/WARM), либо `"unknown"` до фонового дозаполнения (см. RED FLAG #5).
- Логи зафиксировали событие `trade_saved` (DEBUG-уровень).

После успешного выполнения для целой итерации цикла:

- Все валидные новые сделки кита записаны в `whale_trades`.
- Дубликаты (там, где `tx_hash` передавался) — отвергнуты с `"duplicate"`.
- Невалидные сделки — отвергнуты с `"rejected"`, остались в логах.

**Состояние сделки** (в терминах магистрали): сделка зафиксирована в БД. Это **финальное состояние сделки внутри контура `whale_trades`** — дальнейшие изменения этой строки происходят только через side-эффекты downstream-процессов (`category_backfill` дозаполняет `market_category`, `roundtrip_builder` использует строку для реконструкции позиций, но саму строку не модифицирует).

**Связь с следующим шагом магистрали:**

Запись в `whale_trades` **синхронно** активирует DB-trigger `trigger_copy_whale_trade` (по PROJECT_STATE: `whale_trades → paper_trades, status: OK`). Trigger срабатывает в той же транзакции `session.commit()` (блок 11). Это означает, что шаг 3 магистрали — **создание paper-сделки через DB-trigger** — выполняется **до** того, как управление вернётся из `save_trade()` обёртке. Для китов с `copy_status='paper'` создаётся запись в `paper_trades`; для всех остальных trigger ничего не делает.

Шаг 3 — следующий объект описания.

---

## 15. Краткая бизнес-формула шага

```
ВХОД: обёртка вызывает WhaleTradesRepo.save_trade(
        wallet_address, market_id, side, size_usd, price,
        outcome, market_title, market_category, tx_hash,
        source, traded_at
      )
  │
  ├── GATE 1: side ∈ {buy, sell}?        НЕТ → return "rejected"
  ├── GATE 2: size_usd > 0?              НЕТ → return "rejected"
  ├── GATE 3: price > 0?                 НЕТ → return "rejected"
  │
  ├── normalize: market_category → "unknown" если None
  ├── log warn:  outcome пустой (не отклоняет)
  ├── normalize: wallet_address → lower().strip()
  ├── normalize: traded_at → utcnow() если None  (RED FLAG #6)
  │
  ├── whale_id = _lookup_whale_id(wallet_address)
  │   └── SELECT id FROM whales WHERE wallet_address = :wallet
  │       → int | None (молчком поглощает исключения, RED FLAG #4)
  │
  ├── GATE 4: tx_hash непустой?
  │   └── ДА: SELECT 1 FROM whale_trades WHERE tx_hash = :tx_hash
  │       └── существует? → return "duplicate"
  │   └── НЕТ: блок пропущен (HOT/WARM — RED FLAG #2)
  │
  ├── INSERT INTO whale_trades (12 колонок) VALUES (...)
  │   └── whale_id может быть NULL (RED FLAG #1)
  │       tx_hash может быть NULL (RED FLAG #2)
  │       market_category может быть "unknown" (RED FLAG #5)
  │
  ├── session.commit()
  │   └── СИНХРОННО срабатывает DB-trigger trigger_copy_whale_trade
  │       (следующий шаг магистрали, для китов с copy_status='paper')
  │
  └── return "saved"

  При SQLAlchemyError / Exception: rollback + raise (RED FLAG #7 — счётчики
  не экспортируются)
```
