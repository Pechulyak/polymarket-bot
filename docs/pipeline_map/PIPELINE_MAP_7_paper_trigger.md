# PIPELINE_MAP_7 — `trigger_copy_whale_trade` (paper-ветка P1)

**Статус документа:** ACTIVE
**Дата верификации:** 2026-05-27
**Эталон формата:** `PIPELINE_MAP_6_governance_decision.md`

---

## TL;DR

Первый шаг paper-ветки и единственная точка создания paper-сделок в системе. Срабатывает автоматически в момент записи каждой новой сделки кита в `whale_trades` (шаг 2B). Для китов с `copy_status='paper'` рассчитывает размер paper-сделки по proportional Kelly (`our_size = whale_size / estimated_capital × our_bankroll × kelly_fraction`, ограничение через `max_position_pct`) и создаёт запись в `paper_trades`. Для остальных китов сделка пропускается без следов. Дубли отсекаются по `tx_hash` (бессрочно) и по комбинации `(whale, market, side)` в 5-минутном окне. Параметры Kelly хранятся в `strategy_config`. Запись в `paper_trades` появляется со статусом `'open'` и в дальнейшем не модифицируется ни одним production-процессом — paper settlement как отдельный шаг отсутствует, P&L paper-портфеля материализуется на шаге 9.

---

## 1. Назначение шага

Бизнес-смысл: при каждой подтверждённой сделке кита, отобранного для paper-режима на шаге 6, система должна **немедленно сформировать соответствующую paper-сделку** с размером по proportional Kelly. «Немедленно» здесь не маркетинговое слово — paper-сделка появляется в БД в тот же момент, что и исходная сделка кита: успех записи в `whale_trades` означает успех создания paper-сделки, провал — провал обеих.

В контексте paper-ветки шаг 7 — **единственная точка входа**. Без него ни одна downstream-обработка не запускается. В контексте основной магистрали — это side-route шага 2B, не магистральный шаг.

---

## 2. Статус

ACTIVE в production. Trigger существует в БД, `tgenabled = 'O'` (enabled). Регулярно срабатывает при каждой записи в `whale_trades` (по факту — несколько сотен раз в сутки в стационарном режиме).

**Верификация на 2026-05-27:**

| Уровень | Проверка | Результат |
|---|---|---|
| pg_trigger | `SELECT tgname, tgenabled FROM pg_trigger WHERE tgname='trigger_copy_whale_trade'` | enabled |
| Файл | `scripts/create_copy_trigger.sql:7` | существует |
| Git history | `git log scripts/create_copy_trigger.sql` | последний коммит 2026-04-04 (`5d9f797`, BUG-701 days_active fix) |
| Корреляция | строки в `paper_trades` появляются при INSERT в `whale_trades` для paper-китов | подтверждено |

Прямое сравнение `pg_proc.prosrc` с содержимым файла не выполнялось — возможны точечные расхождения в формате при идентичной логике. Если потребуется gold-standard верификация — отдельная задача.

---

## 3. Где живёт

| Элемент | Путь |
|---|---|
| SQL-определение trigger'а и функции | `scripts/create_copy_trigger.sql` |
| Триггер-функция | `copy_whale_trade()` (PL/pgSQL) |
| Trigger на таблице | `trigger_copy_whale_trade ON whale_trades AFTER INSERT FOR EACH ROW` |
| Read-источники | `whales` (capital, copy_status), `strategy_config` (sizing params) |
| Write-цель | `paper_trades` (единственная) |

---

## 4. Контейнер

**N/A.** Database trigger не имеет собственного контейнера — он исполняется внутри процесса PostgreSQL-сервера, в контексте той транзакции, которая инициировала INSERT в `whale_trades`. Для шага 2B это означает, что код trigger'а выполняется в стеке Python-процесса `whale-detector` или `whale-tracker` (тот сервис, который вызвал `WhaleTradesRepo.save_trade()`), внутри блока `session.commit()`. Видимые в Docker контейнеры paper-ветки на этом шаге отсутствуют — первый отдельный контейнер появляется только при гипотетической реализации NotificationWorker (шаг 8, по текущему состоянию не реализован — см. §11).

---

## 5. Триггер запуска

**Синхронный DB-trigger, AFTER INSERT ON `whale_trades`, FOR EACH ROW.**

Активируется PostgreSQL внутри транзакции `WhaleTradesRepo.save_trade()` при коммите INSERT в `whale_trades`. Не привязан к cron, расписанию, polling-циклу или внешнему сервису. Не имеет ручной точки запуска — единственный способ вызвать trigger — выполнить INSERT в `whale_trades`.

Особенности модели запуска:
- **Synchronous** — управление не возвращается из `session.commit()` шага 2B, пока trigger не завершится (успехом или exception'ом).
- **Per-row** — для каждой вставленной строки `whale_trades` trigger вызывается отдельно. Batch INSERT приведёт к N вызовам trigger'а.
- **Без caching** — каждый вызов trigger'а делает свежие SELECT к `whales` и `strategy_config`. Изменение `copy_status` через шаг 6 видно следующему вызову trigger'а немедленно (RTT транзакции).

---

## 6. Алгоритм

Тело функции `copy_whale_trade()` выполняет 7 пунктов в строгом порядке. Логика — без боковых ветвлений, ранний `RETURN NEW` (без INSERT) на любом провале guard'а.

**Пункт 1 — Получение метаданных кита.**
SELECT из `whales` по `wallet_address = NEW.whale_address`: `id`, `copy_status`, `estimated_capital`. Если кит не найден (`v_whale_address IS NULL` после SELECT INTO) — `RETURN NEW` без INSERT. Это естественная защита от race condition: если trade пришёл раньше регистрации кита в `whales`, paper-сделка не создаётся.

**Пункт 2 — Проверка `copy_status = 'paper'`.**
Через `EXISTS(SELECT 1 FROM whales WHERE wallet_address = ... AND copy_status = 'paper')`. Любое другое значение (`'none'`, `'tracked'`, `'live'`, `'excluded'`) — `RETURN NEW` без INSERT. Эта проверка делает trigger «прозрачным» для всех китов вне paper-режима.

**Пункт 3 — Perpetual tx_hash dedup (BUG-505).**
Если `NEW.tx_hash IS NOT NULL`, проверка `EXISTS(SELECT 1 FROM paper_trades WHERE tx_hash = NEW.tx_hash)`. При совпадении — `RETURN NEW` без INSERT. Если `NEW.tx_hash IS NULL`, эта проверка **полностью пропускается** (см. §13 RF2).

**Пункт 4 — 5-минутное окно dedup.**
`EXISTS(SELECT 1 FROM paper_trades WHERE whale_address = v_whale_address AND market_id = NEW.market_id AND side = NEW.side AND created_at >= NOW() - INTERVAL '5 minutes')`. При совпадении — `RETURN NEW` без INSERT. Окно не различает `outcome` (см. §13 RF3) и не фильтрует по `status` (см. §13 RF4).

**Пункт 5 — Чтение sizing-параметров.**
Четыре отдельных SELECT'а из `strategy_config` для `kelly_fraction`, `our_bankroll`, `max_position_pct`, `min_trade_size_usd`. Для каждого параметра — fallback на hardcoded литерал, если строка в `strategy_config` отсутствует или `value IS NULL` (см. §13 RF5 для `our_bankroll`).

**Пункт 6 — Kelly расчёт с CAP.**

```
proportion = NEW.size_usd / NULLIF(COALESCE(estimated_capital, 100000), 0)
our_size_uncapped = proportion × v_our_bankroll × v_kelly_fraction
v_kelly_size = LEAST(our_size_uncapped, v_our_bankroll × v_max_position_pct)
```

Структура `COALESCE → NULLIF` критична: `COALESCE(estimated_capital, 100000)` подставляет 100000 при NULL (когда оператор забыл рассчитать капитал), `NULLIF(..., 0)` превращает 0 в NULL для защиты от деления на ноль. При `estimated_capital = 0` это всё равно даёт `kelly_size = NULL` (см. §13 RF1).

**Пункт 7 — Финальная отсечка и INSERT.**
Если `v_kelly_size < v_min_trade_size_usd` — `RETURN NEW` без INSERT (сделка слишком мала). Иначе — INSERT в `paper_trades` с 13 колонками (см. §9). После INSERT `RETURN NEW` (формальное требование AFTER trigger'а в PostgreSQL).

---

## 7. Формат входных данных

### Implicit input — NEW row из `whale_trades`

Все колонки только что вставленной строки, доступные через `NEW`. Trigger использует:

| Поле NEW | Бизнес-смысл | Дальнейшая обработка |
|---|---|---|
| `whale_address` | wallet кита | lookup в `whales` |
| `market_id` | идентификатор рынка | копируется в `paper_trades`, используется в dedup |
| `market_title` | заголовок рынка (HOT/WARM) | копируется в `paper_trades` |
| `side` | `'buy'` / `'sell'` | копируется, используется в dedup |
| `outcome` | `'YES'` / `'NO'` (опционально) | копируется в `paper_trades` |
| `price` | цена сделки кита | копируется + используется в расчёте `size` |
| `size_usd` | размер сделки кита в USD | основа Kelly proportion + копируется |
| `tx_hash` | хеш транзакции (опционально) | дедуп perpetual + копируется |
| `traded_at` | время сделки | копируется как `created_at` |

NOT NULL-валидация полей `whale_address`, `market_id`, `side`, `price`, `size_usd` происходит **на уровне таблицы `whale_trades`** до вызова trigger'а — PostgreSQL отвергнет INSERT с NULL в любом из этих полей с exception `null value in column "..." violates not-null constraint`, и trigger не будет вызван. То есть trigger получает только валидные NOT NULL значения для этих пяти полей. `tx_hash` и `outcome` — nullable, trigger получает их «как есть».

### Read-input — `whales`

```sql
SELECT id, copy_status, estimated_capital
FROM whales
WHERE wallet_address = NEW.whale_address;
```

Свежее чтение каждого вызова. Изменения, сделанные шагом 6, видны немедленно.

### Read-input — `strategy_config`

Четыре отдельных SELECT'а вида `SELECT value FROM strategy_config WHERE key = '<param>'`. Тип `value` — NUMERIC с разной точностью (`NUMERIC(10,8)` для долей, `NUMERIC(20,8)` для денежных).

Текущие значения в production (на 2026-05-27, без секретов):

| key | value | fallback в коде trigger'а |
|---|---|---|
| `kelly_fraction` | `0.25000000` | `0.25` (совпадает) |
| `our_bankroll` | `100.00000000` | `1000.00` (**расхождение**, см. §13 RF5) |
| `max_position_pct` | `0.05000000` | `0.05` (совпадает) |
| `min_trade_size_usd` | `1.00000000` | `1.00` (совпадает) |

---

## 8. Формат выходных данных

### Прямой выход — INSERT в `paper_trades` или его отсутствие

Trigger ничего не возвращает наружу (нет return value, нет логирования в файл, нет уведомления). Единственный наблюдаемый результат — либо появилась новая строка в `paper_trades`, либо не появилась. Различить «silent skip» от «не сработал вообще» можно только косвенно (например, по факту, что `whale_trades` содержит строку для paper-кита, а соответствующая `paper_trades` отсутствует — значит сработал один из guard'ов).

### Колонки, заполняемые в `paper_trades`

13 колонок INSERT (см. §9). Колонки `paper_trades`, **не** заполняемые trigger'ом:

- `id` — bigserial, заполняется БД.
- `status` — DEFAULT `'open'`, заполняется БД.
- Другие nullable-колонки без DEFAULT остаются NULL (например, `paper_trade_id` в downstream-таблицах, если таковые ссылаются — но FK отсутствуют, см. §13 RF6).

### Косвенный выход — отсутствует downstream

После INSERT в `paper_trades` синхронная цепочка обрывается. По дизайну предполагалось, что второй trigger `trigger_notify_paper_trade` AFTER INSERT ON `paper_trades` будет дополнительно записывать в `paper_trade_notifications` для последующего Telegram-уведомления. **Этот trigger не применён в БД** (см. §11). Поэтому фактический выход шага 7 — только INSERT в `paper_trades`.

---

## 9. Записи в БД

Шаг 7 пишет **в одну таблицу** — `paper_trades`.

### Колонки INSERT (13 штук)

| Колонка | Источник значения | Бизнес-смысл |
|---|---|---|
| `whale_address` | `v_whale_address` (lower) | wallet кита-источника |
| `market_id` | `NEW.market_id` | рынок paper-сделки |
| `market_title` | `NEW.market_title` | заголовок рынка |
| `side` | `NEW.side` | `'buy'` / `'sell'` |
| `outcome` | `NEW.outcome` | `'YES'` / `'NO'` (nullable) |
| `price` | `NEW.price` | цена сделки кита |
| `size` | `NEW.size_usd / NULLIF(NEW.price, 0)` | размер в shares (расчётный) |
| `size_usd` | `NEW.size_usd` | размер сделки кита в USD |
| `kelly_fraction` | `v_kelly_fraction` | применённая Kelly fraction |
| `kelly_size` | `v_kelly_size` (после CAP и min_trade) | размер paper-сделки в USD |
| `created_at` | `NEW.traded_at` | время сделки кита (не `NOW()`) |
| `source` | `v_source` | источник (`'top'` для top-китов, иначе из логики) |
| `tx_hash` | `NEW.tx_hash` | хеш транзакции (nullable) |

### Колонки `paper_trades`, **не** заполняемые шагом 7

- `id` — bigserial, заполняется БД.
- `status` — DEFAULT `'open'`, заполняется БД при INSERT, **никогда не изменяется** ни одним production-процессом (settlement отсутствует, см. §11 и шаг 9 — описание materialized views).

### Constraints и индексы `paper_trades`

| Имя | Тип | Колонки | Комментарий |
|---|---|---|---|
| `paper_trades_pkey` | PRIMARY KEY | `id` | автоинкремент |
| `paper_trades_side_check` | CHECK | `side ∈ ('buy', 'sell')` | единственный CHECK |
| `idx_paper_trades_tx_hash_unique` | UNIQUE partial | `tx_hash WHERE tx_hash IS NOT NULL` | защита от дублей на уровне БД |
| `idx_paper_trades_dedup` | INDEX | `whale_address, market_id, side, created_at DESC` | покрытие 5-min dedup query |
| `idx_paper_trades_created` | INDEX | `created_at DESC` | |
| `idx_paper_trades_market` | INDEX | `market_id` | |
| `idx_paper_trades_whale` | INDEX | `whale_address` | |

**Foreign keys: отсутствуют.** `whale_address`, `market_id`, `tx_hash` — без FK на `whales` / `markets` / `whale_trades` (см. §13 RF6).

NOT NULL: `id`, `whale_address`, `market_id`, `side`, `price`, `size`. Все остальные — nullable. DEFAULT: `kelly_fraction = 0.25`, `created_at = now()`, `source = 'unknown'`.

---

## 10. Условия успеха / частичного успеха / неуспеха

### Per-row (один вызов trigger'а)

| Исход | Условие | Поведение |
|---|---|---|
| **Полный успех — INSERT** | Кит существует, `copy_status='paper'`, tx_hash не дубль, 5-min окно чисто, `kelly_size >= min_trade_size_usd` | Новая строка в `paper_trades`, downstream-цепочка обрывается на этом |
| **Silent skip (race)** | Кит ещё не зарегистрирован в `whales` | `RETURN NEW` без INSERT, потеря paper-сделки навсегда |
| **Silent skip (governance)** | `copy_status ∈ ('none', 'tracked', 'live', 'excluded')` | `RETURN NEW` без INSERT — корректное поведение |
| **Silent skip (tx_hash dup)** | Совпадение perpetual tx_hash | `RETURN NEW` без INSERT |
| **Silent skip (5-min dup)** | Совпадение `(whale, market, side)` за 5 минут | `RETURN NEW` без INSERT |
| **Silent skip (too small)** | `kelly_size < min_trade_size_usd` | `RETURN NEW` без INSERT |
| **Exception → rollback** | Любой PL/pgSQL exception (например, violation CHECK `side`, нарушение UNIQUE `tx_hash` partial index при concurrent INSERT) | Откат всей транзакции 2B → потеря и `whale_trades`, и `paper_trades` |

Все «silent skip» исходы возвращают `NEW` без какой-либо записи в логи. Различить их между собой через БД невозможно — нужен либо `RAISE LOG` в коде trigger'а (отсутствует), либо runtime-инструментация PostgreSQL.

### Per-batch (одна итерация upstream-процесса)

Шаг 2B обычно вызывается в цикле по N сделкам кита. Каждый вызов `save_trade()` — отдельная транзакция (`session.commit()` после каждой записи в текущей реализации), поэтому exception в trigger'е одной сделки откатывает только её, а не всю партию. Если бы шаг 2B перешёл на batch-commit, exception в trigger'е одной строки откатил бы всю партию — на текущей реализации это не риск.

---

## 11. Зависимости

### Upstream

- **Шаг 2B** (`WhaleTradesRepo.save_trade()`) — единственный источник вызовов trigger'а. Без INSERT в `whale_trades` trigger не активируется.
- **Шаг 6** — формирует значение `whales.copy_status`. Без `copy_status='paper'` для конкретного кита его сделки не превращаются в paper-сделки (Пункт 2 алгоритма).
- **`strategy_config`** — источник sizing-параметров. Записи в эту таблицу делаются вручную через DBeaver или migration-скрипты. UI/CLI для обновления отсутствует.
- **`whales.estimated_capital`** — рассчитывается на шаге 6 при переходе `tracked → paper` (один из 4 методов в `WHALE_STATUS_TRANSITIONS.md` §11.1).

### Downstream (фактическое)

- **Шаг 9** (`paper_simulation_pnl`, `paper_portfolio_state`, `whale_pnl_summary` materialized views) — единственный потребитель `paper_trades` в production. Refresh через cron `15 */2 * * *`. Связь с шагом 7 — **асинхронная через таблицу `paper_trades`**: INSERT шага 7 виден следующему refresh шага 9.

### Downstream (по дизайну, но не реализовано)

- **`trigger_notify_paper_trade`** AFTER INSERT ON `paper_trades` — определён в `scripts/add_telegram_notifications.sql`, но **не применён в БД** (`SELECT tgname FROM pg_trigger WHERE tgname='trigger_notify_paper_trade'` возвращает 0 строк). Таблица `paper_trade_notifications` существует, но не пополняется. По текущему состоянию paper-ветка не уведомляет о новых сделках через Telegram — это известное ограничение. Возможная будущая интеграция: применить SQL-файл `add_telegram_notifications.sql` и активировать NotificationWorker (шаг 8 в плане paper-ветки). Скоуп возможной активации — отдельная задача, не часть шага 7.
- **`trades`-таблица** — также unused, по аналогии с `paper_trade_notifications`. Trigger в неё не пишет.

### External

Нет. Trigger не делает сетевых вызовов, не пишет в файлы, не использует расширения PostgreSQL за пределами стандартного `plpgsql`.

---

## 12. Метрики и мониторинг

**Отсутствуют как отдельный слой для шага 7.** В коде trigger'а нет `RAISE LOG` / `RAISE NOTICE`, нет инкремента счётчиков, нет записей в служебные таблицы аудита. Косвенные сигналы:

- **Количество INSERT'ов в `paper_trades`** — наблюдаемо через `SELECT COUNT(*) FROM paper_trades WHERE created_at > NOW() - INTERVAL '1 day'`. Само по себе не различает «trigger сработал верно, kelly_size ниже min_trade» от «trigger не сработал вообще».
- **Аномалии `kelly_size`** — `kelly_size IS NULL` в недавних строках сигнализирует о RF1 или RF2 (см. §13).
- **Покрытие paper-китов** — `SELECT wallet_address FROM whales WHERE copy_status='paper'` против `SELECT DISTINCT whale_address FROM paper_trades WHERE created_at > ...` показывает китов, для которых ожидались paper-сделки, но они не появились.

Возможность системного мониторинга шага 7 целесообразно рассмотреть в скоупе шага 9 (materialized views) — некоторые из этих агрегаций естественно ложатся на mat view.

---

## 13. RED FLAGs

### RF1 — `estimated_capital = 0` приводит к `kelly_size = NULL` в `paper_trades`

При `whales.estimated_capital = 0` (не NULL, а ноль — например, оператор записал ноль вручную или результат расчёта на шаге 6 дал ноль) расчёт Kelly proceduralно даёт NULL: `COALESCE(0, 100000) = 0` (COALESCE срабатывает только на NULL, не на ноль), затем `NULLIF(0, 0) = NULL`, далее `size_usd / NULL = NULL`, и весь `our_size_uncapped = NULL`. `LEAST(NULL, anything) = NULL`. Сравнение `NULL < min_trade_size_usd` даёт UNKNOWN (не TRUE), поэтому отсечка пункта 7 не срабатывает, и **INSERT выполняется с `kelly_size = NULL`**.

Колонка `paper_trades.kelly_size` — nullable, БД примет такую запись. Шаг 9 (materialized views), агрегируя `kelly_size`, получит NULL → искажение P&L paper-портфеля без явной ошибки.

Защита: либо ввести CHECK `estimated_capital > 0` на `whales`, либо guard в trigger'е `IF v_estimated_capital = 0 THEN RETURN NEW`. Ни одно не реализовано.

### RF2 — `tx_hash IS NULL` пропускает perpetual dedup

Проверка `IF NEW.tx_hash IS NOT NULL AND EXISTS(...)` — оба условия в AND. При `tx_hash IS NULL` первое условие сразу FALSE, проверка не выполняется, защита от дублей сводится **только** к 5-минутному окну. Сделки старше 5 минут с пропущенным tx_hash могут породить дубль paper-сделки при повторной обработке.

`tx_hash IS NULL` возникает в HOT/WARM-циклах шага 2B (см. RF#2 шага 2B `PIPELINE_MAP_2B_whale_trades_write.md`), когда API не возвращает хеш транзакции. Для таких сделок защита неполная.

### RF3 — 5-минутное окно dedup не различает `outcome`

WHERE-условие 5-min dedup: `whale_address = ... AND market_id = ... AND side = ... AND created_at >= NOW() - INTERVAL '5 minutes'`. `outcome` (`YES`/`NO`) **не включён**. Если кит на одном рынке за 5 минут купил долю YES и долю NO (легитимный hedge или арбитраж), вторая сделка будет отвергнута как дубль, и paper-сделка для неё не создастся.

Это false-positive дедупликации, приводящий к недопредставленности hedge-стратегий китов в paper-портфеле. На рынках бинарных контрактов (Polymarket) — ненулевой риск.

### RF4 — 5-минутное окно dedup не фильтрует по `status`

WHERE-условие 5-min dedup не включает `status`. Скрытая бомба для гипотетического будущего: если paper settlement будет когда-либо введён через UPDATE `paper_trades.status='closed'`, и через 4 минуты после закрытия позиции кит откроет аналогичную (рестарт стратегии), 5-min dedup отвергнет вторую сделку как дубль закрытой — что некорректно. На текущей архитектуре (status навсегда `'open'`) не проявляется. Фиксируется для skoupa шага 9 и будущих изменений архитектуры paper-ветки.

### RF5 — Расхождение fallback `our_bankroll`

В теле trigger'а fallback на отсутствие строки `our_bankroll` в `strategy_config` — литерал `1000.00`. Реальное production-значение — `100.00`. Расхождение в 10×.

Сценарий проявления: `DELETE FROM strategy_config WHERE key = 'our_bankroll'` или `UPDATE strategy_config SET value = NULL WHERE key = 'our_bankroll'`. Следующий же trade паpper-кита посчитает sizing от `our_bankroll = 1000` — в 10× больше production. Без алертов, без логов, обнаруживается только по аномалии в `paper_trades.kelly_size` или ручному audit'у. Аналогичные fallback'ы для `kelly_fraction = 0.25`, `max_position_pct = 0.05`, `min_trade_size_usd = 1.00` совпадают с production-значениями — расхождение только по `our_bankroll`.

### RF6 — Отсутствие FK на `paper_trades`

`whale_address`, `market_id`, `tx_hash` в `paper_trades` — без foreign keys на `whales`, `markets`, `whale_trades` соответственно. Возможные последствия:

- DELETE из `whales` (если когда-либо понадобится — сейчас на этой таблице полагаются как на референс) не каскадирует в `paper_trades`, появляются orphaned записи.
- DELETE из `whale_trades` (например, при cleanup или миграции) не каскадирует в `paper_trades`. Шаг 9, джойнящий `paper_trades × whale_trade_roundtrips` через `whale_address + market_id`, увидит paper-сделки без соответствующих roundtrip'ов → искажение P&L.
- Опечатки `whale_address` в `whales` (теоретически — на уровне governance) не отлавливаются БД и приводят к paper-сделкам с «битым» wallet.

Архитектурный технический долг. Добавление FK сейчас потребует cleanup orphaned-записей (объём не верифицирован).

### RF7 — Отсутствие CHECK constraints на `source`, `status`, `outcome`

Из колонок `paper_trades` CHECK имеет только `side ∈ ('buy', 'sell')`. `source`, `status`, `outcome` принимают произвольные строки. Опечатка (`'YES_'` вместо `'YES'`, `'opn'` вместо `'open'`) пройдёт INSERT и проявится только при агрегации в шаге 9 как «лишнее» значение в GROUP BY. На текущей фазе trigger всегда подставляет валидные значения, но любая будущая модификация trigger'а или ручной INSERT в `paper_trades` не защищены БД-валидацией.

---

## 14. Связь со следующим шагом paper-ветки

**Следующий шаг paper-ветки — шаг 9** (`paper_simulation_pnl`, `paper_portfolio_state`, `whale_pnl_summary` materialized views). Связь — **асинхронная через таблицу `paper_trades`**: INSERT шага 7 виден следующему refresh шага 9.

Cron расписание refresh — `15 */2 * * *` (раз в 2 часа, на 15-й минуте). Задержка между записью paper-сделки и её появлением в P&L агрегатах — до 2 часов плюс время фактического REFRESH MATERIALIZED VIEW.

Шаг 8 (NotificationWorker) **не существует** в текущей production-архитектуре — `trigger_notify_paper_trade` не применён, `paper_trade_notifications` не пополняется. Возможная будущая интеграция — отдельная задача, не часть скоупа шага 7.

---

## 15. Краткая бизнес-формула шага

```
ВХОД: commit шага 2B вставил строку в whale_trades для кита с copy_status='paper'
      NEW = {whale_address, market_id, side, price, size_usd, tx_hash, traded_at,
             market_title, outcome}  (NOT NULL поля гарантированы валидацией whale_trades)
  │
  │ trigger AFTER INSERT ON whale_trades FOR EACH ROW
  │ исполняется synchronously в той же транзакции
  ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │ Пункт 1: SELECT id, copy_status, estimated_capital               │
  │          FROM whales WHERE wallet_address = NEW.whale_address    │
  │   v_whale_address IS NULL → RETURN NEW (race condition guard)    │
  ├──────────────────────────────────────────────────────────────────┤
  │ Пункт 2: copy_status = 'paper' ?                                 │
  │   НЕТ → RETURN NEW (silent skip)                                 │
  ├──────────────────────────────────────────────────────────────────┤
  │ Пункт 3: perpetual tx_hash dedup                                 │
  │   tx_hash IS NOT NULL AND EXISTS in paper_trades → RETURN NEW    │
  │   tx_hash IS NULL → проверка пропущена (RF2)                     │
  ├──────────────────────────────────────────────────────────────────┤
  │ Пункт 4: 5-минутное окно по (whale, market, side)                │
  │   EXISTS → RETURN NEW (outcome не различается — RF3)             │
  ├──────────────────────────────────────────────────────────────────┤
  │ Пункт 5: чтение sizing-параметров из strategy_config             │
  │   kelly_fraction, our_bankroll, max_position_pct,                │
  │   min_trade_size_usd                                             │
  │   fallback в коде trigger'а при IS NULL                          │
  ├──────────────────────────────────────────────────────────────────┤
  │ Пункт 6: Kelly расчёт                                            │
  │   proportion = NEW.size_usd / NULLIF(COALESCE(capital, 100000),0)│
  │   our_size = proportion × bankroll × kelly_fraction              │
  │   v_kelly_size = LEAST(our_size, bankroll × max_position_pct)    │
  │   estimated_capital = 0 → v_kelly_size = NULL (RF1)              │
  ├──────────────────────────────────────────────────────────────────┤
  │ Пункт 7: финальная отсечка                                       │
  │   v_kelly_size < min_trade_size_usd → RETURN NEW                 │
  │   иначе:                                                         │
  │   INSERT INTO paper_trades                                       │
  │     (whale_address, market_id, market_title, side, outcome,      │
  │      price, size, size_usd, kelly_fraction, kelly_size,          │
  │      created_at, source, tx_hash)                                │
  │   VALUES (v_whale_address, NEW.market_id, NEW.market_title,      │
  │      NEW.side, NEW.outcome, NEW.price,                           │
  │      NEW.size_usd / NULLIF(NEW.price, 0), NEW.size_usd,          │
  │      v_kelly_fraction, v_kelly_size, NEW.traded_at,              │
  │      v_source, NEW.tx_hash)                                      │
  │   status='open' через DEFAULT                                    │
  │   RETURN NEW                                                     │
  └──────────────────────────────────────────────────────────────────┘
  ▼
ВЫХОД: либо новая строка в paper_trades (status='open' навсегда),
       либо silent skip.
       Следующая ступень paper-ветки — шаг 9 (mat views),
       асинхронно через cron `15 */2 * * *`.

  Notification-механизм (`trigger_notify_paper_trade`) НЕ применён в БД —
  возможная будущая интеграция, в текущей архитектуре отсутствует.
```

---

## 16. Open questions

1. **Происхождение fallback `our_bankroll = 1000.00`** — артефакт ранней версии (production изначально был `1000`, позднее снижен до `100` через `strategy_config`) или намеренный design (`1000` как «defensive»). Не блокирует, но имеет значение при будущих изменениях sizing-логики.
2. **Поведение trigger'а при `whales.estimated_capital < 0`** (теоретически возможно при ошибке расчёта на шаге 6 — нет CHECK > 0 на колонке). Не верифицировано отдельно. Гипотетически: отрицательная proportion → отрицательный `kelly_size` → может пройти `< min_trade_size_usd` отсечку как «слишком малая» (если `min` положительный), но при `min=1` и отрицательном `kelly_size`: `-50 < 1` истинно → silent skip. Защита косвенная.
3. **Корреляция `pg_proc.prosrc` с файлом `scripts/create_copy_trigger.sql`** — прямое сравнение не выполнялось. Возможны точечные расхождения при идентичной логике (например, форматирование). Отдельная задача.
4. **Когда (и нужно ли) применить `add_telegram_notifications.sql`** — относится к скоупу шага 8 (notification-механизм). Пока не часть paper-ветки в production.

---

**Конец документа.**
