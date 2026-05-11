# ШАГ 1. ПОДКЛЮЧЕНИЕ К POLYMARKET DATA API (read path)

## Краткая характеристика (TL;DR)

Контейнер `whale-detector` обращается к публичному Polymarket Data API в **четырёх режимах**:

- **Discovery (`WhaleDetector._polymarket_poll_loop`)** — каждые 60 сек забирает свежие сделки со всего рынка для поиска новых активных адресов
- **Targeted paper (`WhaleDetector._paper_poll_loop`)** — каждые 30 сек обходит всех paper-китов из БД (критический путь)
- **Targeted tracked (`WhaleDetector._tracked_poll_loop`)** — каждые 300 сек (5 мин) обходит всех tracked-китов (некритический путь)
- **Targeted tier-based (`WhalePoller.run_hot_polling` / `run_warm_polling`, инстанцируется внутри `RealTimeWhaleMonitor`)** — каждые 14 400 сек (4 ч) для HOT-китов и 86 400 сек (24 ч) для WARM-китов

Таймаут 30 сек, retry отсутствует, локального rate-limiter нет (в отличие от CLOB-клиента того же проекта). При росте числа китов нагрузка растёт линейно без защиты. Все четыре режима работают в одном процессе `whale-detector` и делят один inсtance `PolymarketDataClient` без общего лимитера.

---

## 1. Назначение шага

Шаг обеспечивает чтение данных о сделках китов из публичного Polymarket Data API. Это единственный внешний источник входных данных для всего whale-контура проекта — без него не работают ни обнаружение новых китов, ни отслеживание их сделок, ни paper-копирование.

Бизнес-смысл: получить «сырьё» — список свежих сделок по адресам трейдеров — и передать его дальше в pipeline.

---

## 2. Статус

**CONFIRMED-ACTIVE** для основного канала (`PolymarketDataClient`): подтверждён триггер (docker-compose сервис `whale-detector`), точка входа, 5 циклов с верифицированными интервалами.

| `whale_poller.py` | WhalePoller | ACTIVE — инстанцируется внутри `RealTimeWhaleMonitor` (`real_time_whale_monitor.py:222`), запускается через `whale-detector` сервис |

Дата верификации: 2026-05-09.

---

## 3. Исходные файлы

В проекте **два независимых канала** обращения к одному и тому же `data-api.polymarket.com`:

**Канал A — основной клиент.**
`src/research/polymarket_data_client.py` — класс `PolymarketDataClient`. HTTP-библиотека: `aiohttp`. Используется пятью production-модулями: `whale_detector.py`, `whale_poller.py`, `real_time_whale_monitor.py`, `run_whale_detection.py`, `src/research/__init__.py`.

**Канал B — bypass.**
`src/research/whale_tracker.py` — класс `WhaleTracker` хранит собственную константу `DATA_API_URL` (стр. 184), HTTP-библиотека тоже `aiohttp`, вызовы через собственную сессию в методах `fetch_whale_positions` (стр. 257) и `fetch_whale_trades` (стр. 338). `PolymarketDataClient` не используется.

**Обоснование наличия двух каналов:** в коде отсутствует.
Проверены docstrings класса `WhaleTracker` (стр. 173–182), методов `fetch_whale_positions` (стр. 245–256) и `fetch_whale_trades` (стр. 323–337), module-level docstring (стр. 2–15). Все они описывают, **что** делает `WhaleTracker`, но не объясняют, **почему** он повторяет функциональность `PolymarketDataClient` на той же библиотеке `aiohttp`. TODO/FIXME про дублирование тоже отсутствуют. Это RED FLAG #1 — архитектурное решение без обоснования.

---

## 4. Контейнер

`whale-detector` — отдельный docker-compose сервис.
Команда запуска: `python src/run_whale_detection.py`.
Все 5 поллинг-циклов работают внутри одного процесса этого контейнера.

---

## 5. Триггер запуска и расписание

Триггер: запуск контейнера `whale-detector` через docker-compose.

Внутри контейнера работают **5 циклов, обращающихся к Data API:**

РежимМетод / ЦиклИнтервал sleepФайл:строка sleepИсточник интервалаDiscoveryWhaleDetector._polymarket_poll_loop60 секwhale_detector.py:1383литерал asyncio.sleep(60), конструктор-параметр polymarket_poll_interval_seconds=60 (whale_detector.py:1378)Targeted paperWhaleDetector._paper_poll_loop30 секwhale_detector.py:1405литерал asyncio.sleep(30)Targeted trackedWhaleDetector._tracked_poll_loop300 сек (5 мин)whale_detector.py:1424литерал asyncio.sleep(300)Targeted tier-based HOTWhalePoller.run_hot_polling14 400 сек (4 ч)whale_poller.py:446константа HOT_POLL_INTERVAL_SECONDS (whale_poller.py:42) через config.get("hot_poll_interval", ...)Targeted tier-based WARMWhalePoller.run_warm_polling86 400 сек (24 ч)whale_poller.py:489константа WARM_POLL_INTERVAL_SECONDS (whale_poller.py:43) через config.get("warm_poll_interval", ...)
WhalePoller инстанцируется внутри RealTimeWhaleMonitor (real_time_whale_monitor.py:222), который, в свою очередь, создаётся в run_whale_detection.py:197.

Самый частый канал чтения = paper poll (30 сек).
Latency: near-real-time для paper-китов, batch для HOT/WARM.

---

## 6. Алгоритм шага

### Режим Discovery (один запрос на цикл)

1. Каждые 60 сек `_polymarket_poll_loop` вызывает `fetch_recent_trades(limit=500)` (`whale_detector.py:1440`)
2. Клиент шлёт `GET /trades?limit=500` на `https://data-api.polymarket.com`
3. Возвращается список последних 500 сделок **по всему рынку Polymarket** (не по конкретному киту)
4. Метод `aggregate_by_address()` группирует сделки по адресам
5. Полученные адреса передаются в `_save_whale_to_db()` для записи / обновления в таблице `whales`

### Режим Targeted (запрос на каждого кита из БД)

1. Цикл (paper / tracked / hot / warm) делает SQL-выборку адресов:
   - paper: `SELECT wallet_address FROM whales WHERE copy_status = 'paper'` (`whale_detector.py:1653–1657`)
   - tracked: `SELECT wallet_address FROM whales WHERE copy_status = 'tracked'` (`whale_detector.py:1787–1791`)
   - hot/warm: `WHERE tier = 'HOT'/'WARM' ORDER BY last_targeted_fetch_at ASC NULLS FIRST` (`whale_poller.py:128–139`)
2. **Numeric cap отсутствует** — обходятся все строки выборки
3. Для каждого адреса вызывается `fetch_trader_trades(trader_address, limit=N)`
4. Между запросами — `asyncio.sleep(0.3)` (комментарий «Rate limit: 0.3s between requests»)
5. Клиент шлёт `GET /trades?user=0x...&limit=N`, возвращается список сделок этого адреса

Значения `limit` для разных циклов:

| Вызов | limit |
|-------|-------|
| `_paper_poll_loop` (`whale_detector.py:1711`) | 50 |
| `_tracked_poll_loop` (`whale_detector.py:1845`) | 50 |
| `WhalePoller.poll_whale` first fetch (`whale_poller.py:199`) | 100 |
| `WhalePoller.poll_whale` subsequent fetch (`whale_poller.py:187`) | 500 |
| `WhaleDetector._fetch_initial_history` bootstrap (`whale_detector.py:1110`) | 500 |

### Обработка дублей

На уровне самого шага 1A дедупликации нет — клиент возвращает всё, что прислал API. Уникальность сделок гарантируется на уровне БД через UNIQUE constraint на `tx_hash` в таблице `whale_trades` (это уже downstream-шаг, не 1A).

При парсинге пропускаются:
- сделки без `proxyWallet` (`polymarket_data_client.py:213–214`)
- сделки, на которых упал парсер отдельной записи (`polymarket_data_client.py:240`)

Остальные дубли (например, повторное появление одной и той же сделки в двух последовательных вызовах из-за окна перекрытия) попадают в downstream и фильтруются там.

---

## 7. Формат входных данных

**На вход клиенту:**
- `trader_address` (для targeted) — адрес кита, нормализуется в lower-case (`polymarket_data_client.py:262`)
- `limit` — числовой литерал в коде вызова (см. §6)
- HTTP-сессия (создаётся лениво при первом вызове через `_get_session()`, `polymarket_data_client.py:128–132`)

**Параметры запроса к API:**
- `limit` — число возвращаемых сделок
- `user` — адрес в lower-case (только для targeted)
- `Authorization: Bearer <token>` — опциональный заголовок, отправляется если задан `settings.polymarket_api_key`. Без токена API работает в публичном режиме.

---

## 8. Формат выходных данных

API отдаёт JSON-массив сделок. Клиент парсит каждую запись и складывает в Python-объект `TradeWithAddress` (`@dataclass` в `polymarket_data_client.py:31–63`).

**Поля API → внутренние поля `TradeWithAddress`** (mapping в `_parse_trades`, `polymarket_data_client.py:199–244`):

| Поле API | Внутреннее поле | Преобразование | Строка |
|----------|-----------------|----------------|--------|
| `proxyWallet` | `trader` | `.lower()` | `polymarket_data_client.py:224` |
| `transactionHash` | `tx_hash` | — | — |
| `conditionId` | `condition_id` | snake_case | — |
| `side` | `side` | `.upper()` | `polymarket_data_client.py:228` |
| `size` | `size` | `Decimal()`, default `Decimal("0")` | `polymarket_data_client.py:219` |
| `price` | `price` | `Decimal()`, default `Decimal("0")` | `polymarket_data_client.py:220` |
| `timestamp` | `timestamp` | `int()`, default `0` | `polymarket_data_client.py:232` |
| `title` | `market_title` | snake_case, default `""` | `polymarket_data_client.py:233` |
| `outcome` | `outcome` | default `""` | `polymarket_data_client.py:234` |
| `outcomeIndex` | `outcome_index` | default `None` | `polymarket_data_client.py:235` |
| `name` | `name` | default `""` | `polymarket_data_client.py:236` |
| `asset` | `asset` | — | — |
| — | `size_usd` | вычисляется как `size * price` | `polymarket_data_client.py:221` |

Дополнительная структура `AggregatedTraderStats` (`polymarket_data_client.py:66–88`) — результат агрегации `aggregate_by_address()` для discovery-режима.

---

## 9. Записи в БД

На самом шаге 1A прямой записи в БД нет — это read-only API-вызов.
Запись в `whale_trades`, `whales` происходит в downstream-шагах (whale ingestion, whale tracker), которые описываются отдельно.

Constraints / индексы / FK: N/A (нет целевой таблицы).
Idempotency: N/A (read-only).

---

## 10. Условия успеха / частичного успеха / неуспеха

**Успех:** HTTP 200, JSON распарсен, объекты `TradeWithAddress` сформированы, переданы в downstream.

**Частичный успех:** ответ получен, но часть отдельных сделок не парсится — каждая такая сделка пропускается (`polymarket_data_client.py:240`) с DEBUG-логом `polymarket_parse_trade_error`. Pipeline продолжает работу с остальными.

**Неуспех (для конкретного вызова):**
- HTTP ≠ 200 → `PolymarketDataError` (`polymarket_data_client.py:167–175` для `fetch_recent_trades`, `:272–274` для `fetch_trader_trades`)
- Сетевая ошибка / таймаут (`aiohttp.ClientError`) → `PolymarketDataError`, лог `polymarket_request_failed` (`polymarket_data_client.py:195`, `:291`)
- Битый JSON (HTTP 200 + некорректный ответ) → **необработанный `JSONDecodeError`** улетает наверх (см. §13 RED FLAG #6)

При сбое одного вызова в targeted-режиме цикл переходит к следующему адресу. Контейнер не падает.

---

## 11. Зависимости

**Upstream:** внешний публичный сервис `https://data-api.polymarket.com` (нет SLA от провайдера).

**Downstream consumers (в одном процессе с шагом 1A):**
- `WhaleDetector` — discovery новых китов, обновление активности paper/tracked
- `WhalePoller` — периодическое обновление по тирам HOT/WARM
- `RealTimeWhaleMonitor` — координация поллеров
- `WhaleTracker` (через bypass-канал) — статус неподтверждён

**SQL-зависимости от таблицы `whales`:**

| Цикл | Тип | Колонки SELECT | Колонки UPDATE/INSERT |
|------|-----|----------------|------------------------|
| `_polymarket_poll_loop` | SELECT + INSERT/UPDATE | `wallet_address` | `wallet_address, total_trades, total_volume_usd, avg_trade_size_usd, risk_score, qualification_status, trades_last_3_days, trades_last_7_days, days_active_7d, days_active_30d, source_new, notes, last_active_at, updated_at` (`whale_detector.py:1005–1033`) |
| `_paper_poll_loop` | SELECT only | `wallet_address` (WHERE `copy_status='paper'`) | — (пишет только в `whale_trades`, не в `whales`) |
| `_tracked_poll_loop` | SELECT only | `wallet_address` (WHERE `copy_status='tracked'`) | — (пишет только в `whale_trades`, не в `whales`) |
| `WhalePoller.run_hot_polling` | SELECT + UPDATE | `id, wallet_address, tier, last_targeted_fetch_at, days_active_7d, last_active_at` | `last_targeted_fetch_at, last_active_at, tier, days_active_7d, trades_count, updated_at` (`whale_poller.py:328–342`) |
| `WhalePoller.run_warm_polling` | SELECT + UPDATE | `id, wallet_address, tier, last_targeted_fetch_at, days_active_7d, last_active_at` | `last_targeted_fetch_at, last_active_at, tier, days_active_7d, trades_count, updated_at` (`whale_poller.py:328–342`) |

**External services:** rate limits Polymarket Data API — не задокументированы и не учтены в коде (см. §13 RED FLAG #8).

---

## 12. Наблюдаемость

Логирование через `structlog`:

| Событие | Уровень | Структурированные ключи | Строка |
|---------|---------|--------------------------|--------|
| `polymarket_data_client_initialized` | INFO | — | `polymarket_data_client.py:126` |
| `polymarket_api_error` | ERROR | `status`, `error` | `polymarket_data_client.py:170` |
| `polymarket_trades_fetched` | INFO | `count`, `total_raw` | `polymarket_data_client.py:187–191` |
| `polymarket_request_failed` | ERROR | `error` | `polymarket_data_client.py:196` |
| `polymarket_trader_trades_fetched` | INFO | `trader[:10]`, `count` | `polymarket_data_client.py:283–287` |
| `polymarket_aggregated` | INFO | `unique_traders`, `total_trades` | `polymarket_data_client.py:339–343` |
| `polymarket_parse_trade_error` | DEBUG | `error` | `polymarket_data_client.py:241` |

Адреса трейдеров частично редактируются (`trader[:10]`).

Метрик/алертов специально на состояние Data API в текущем скоупе не обнаружено.

---

## 13. Особые случаи и риски

**RED FLAG #1 — Bypass-канал без обоснования.** `WhaleTracker` делает прямые `aiohttp`-вызовы, минуя `PolymarketDataClient`. Обе реализации используют **одну и ту же** HTTP-библиотеку, но разные сессии и разную нормализацию полей. В коде (docstrings, комментарии, TODO) объяснений дублирования нет. Следствие: разное поведение при ошибках в двух местах, потенциальные тихие расхождения данных, удвоенная поверхность для багов.

**RED FLAG #2 — `WhaleTracker` без триггера.** Модуль существует как библиотека, но в production-петлях контейнера `whale-detector` его вызовы не подтверждены. Возможно, привязан к `main.py` (статус `PARTIAL, no execution` в `PROJECT_STATE.md`) — то есть фактически dead code. Требует отдельной верификации в шаге №8 карты.

**RED FLAG #3 — Dead config.** Переменная `polymarket_api_url` в `src/config/settings.py:68` (значение `https://api.polymarket.com`) не используется ни одним модулем. Кандидат на удаление.

**RED FLAG #4 — Hardcoded base URL.** В обоих каналах URL зашит в код. Override через env невозможен (даже при наличии переменной из RED FLAG #3).

**RED FLAG #5 — Overlap по адресам между циклами.** Один и тот же кит может одновременно попадать в выборку нескольких циклов (например, `copy_status='paper'` И `tier='HOT'`). Тогда его опросят оба цикла независимо — двойные запросы к API по одному адресу. Дедупликации между циклами нет.

**RED FLAG #6 — JSON-парсинг не защищён.** Если API вернёт HTTP 200 с битым JSON, `json.JSONDecodeError` улетает наверх неотловленным (`polymarket_data_client.py:177`, нет try/except). `aiohttp.ClientError` это исключение не покрывает. Pipeline может упасть на одной кривой response.

**RED FLAG #7 — Нет retry.** Один сбой API = пропущенный цикл для всех адресов в этой итерации. Нет backoff, нет повторных попыток. Для paper poll (30 сек) каждый «пропуск» означает потерю окна свежих сделок.

**RED FLAG #8 — Нет rate limiting в Data API клиенте.**
- Нет обработки HTTP 429
- Нет уважения `Retry-After`
- Нет превентивного троттлинга
- Нет упоминаний rate limits Polymarket Data API в коде проекта вообще

При этом `execution/polymarket/client.py` (CLOB) имеет полноценный rate limit: `MAX_REQUESTS_PER_MINUTE=100`, метод `_apply_rate_limit()`, обработка 429 с `Retry-After`. То есть в проекте есть готовый паттерн, но к Data API он не применён.

**RED FLAG #9 — Inconsistency в логировании.** `fetch_recent_trades` логирует текст ошибки при HTTP ≠ 200 (`polymarket_data_client.py:170`), `fetch_trader_trades` — нет (`polymarket_data_client.py:272`). Один класс, разное поведение. При диагностике инцидентов часть ошибок будет «слепой».

**RED FLAG #10 — Parse errors на уровне DEBUG.** Когда отдельная сделка не парсится (`polymarket_data_client.py:241`), ошибка пишется только на DEBUG. В production обычно INFO/WARN — значит, эти ошибки **невидимы**. Можем тихо терять трейды и не знать.

**RED FLAG #11 — Нет защиты от NaN/Inf при `size * price`.** `size_usd` вычисляется как Decimal-произведение без guard (`polymarket_data_client.py:221`). Если API однажды вернёт экзотическое значение — поедут данные дальше по pipeline.

**RED FLAG #12 — Линейный рост нагрузки без cap.** Ни один из 4 targeted-циклов не имеет численного ограничения на число опрашиваемых адресов. При универсе в 50 paper-китов: 50 запросов за 30 сек (~1.67 req/s). При 100 китах — 3.33 req/s. Без знания rate limit Polymarket это слепая зона.

**RED FLAG #13 — `0.3s` sleep вместо rate limiter.** Между per-whale запросами стоит `asyncio.sleep(0.3)` (`whale_detector.py:1708`, `:1842`; `whale_poller.py:437`, `:481`). Это не учитывает время выполнения запроса, не реагирует на 429, не считает запросы в окне. При параллельной работе двух циклов суммируется неконтролируемо.

---

## 14. Результат шага

После успешного выполнения:
- получены свежие сделки по адресам китов из Data API
- данные приведены к `TradeWithAddress` (с lower-case адресами, нормализованными типами)
- объекты переданы в downstream-шаги pipeline для записи в БД и анализа

Без этого шага все последующие узлы whale-контура не получают входные данные.

---

## 15. Краткая бизнес-формула шага

```
docker-compose: whale-detector
    → run_whale_detection.py
        ├─ Discovery: каждые 60s
        │   └─ fetch_recent_trades(limit=500)
        │       → GET /trades?limit=500
        │       → 500 свежих сделок всего рынка
        │       → aggregate_by_address()
        │       → write to whales (14 колонок)
        │
        ├─ Targeted paper: каждые 30s
        │   └─ SQL: copy_status='paper' (без LIMIT)
        │       → для каждого: fetch_trader_trades(addr, limit=50)
        │       → GET /trades?user=0x...&limit=50
        │       → между запросами sleep(0.3)
        │       → write to whale_trades (не в whales)
        │
        ├─ Targeted tracked: каждые 300s
        │   └─ SQL: copy_status='tracked' (без LIMIT)
        │       → fetch_trader_trades(addr, limit=50)
        │       → write to whale_trades (не в whales)
        │
        └─ Targeted HOT/WARM: каждые 4h / 24h
            └─ SQL: tier='HOT'/'WARM' (без LIMIT)
                → fetch_trader_trades(addr, limit=100 или 500)
                → update whales (6 колонок)

    Параллельно (триггер не подтверждён):
        WhaleTracker → собственный aiohttp → GET /trades / /positions