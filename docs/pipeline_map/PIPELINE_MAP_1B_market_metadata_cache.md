# ШАГ 1B. ПОДКЛЮЧЕНИЕ К POLYMARKET CLOB + GAMMA API (market metadata read path)

## Краткая характеристика (TL;DR)

Контейнер `whale-detector` обращается к публичному Polymarket CLOB API за метаданными рынка в **одном режиме**:

- **On-trade lookup** — каждый раз, когда обрабатывается новая сделка кита (через `WhaleDetector.save_trade_to_db` или `RealTimeWhaleMonitor._on_trade_signal`), для её `market_id` запрашиваются название рынка и категория. Запрос выполняется только если данных по этому `market_id` ещё нет в локальном кеше процесса; повторные обращения к тому же рынку обслуживаются мгновенно из памяти.

Один эндпоинт (`GET https://clob.polymarket.com/markets/{market_id}`), из ответа извлекаются два поля: `question` (название) и `tags` (категория). Таймаут 30 сек, retry до 3 раз с linear backoff, локальный rate-limiter 100 req/min на процесс. Кеш — in-memory dict без TTL и без верхнего предела размера; два cache-модуля (`market_title_cache`, `market_category_cache`) имеют независимые dict'ы, поэтому первый запрос к рынку даёт **два** API-вызова к одному и тому же URL.

В контейнере `bot` (Phase 2B, heartbeat-only) шаг 1B **не активен** — модули, импортирующие cache-функции (`virtual_bankroll`, `copy_trading_engine`), заморожены и не инстанцируются в `main.py`. Все потенциальные вызовы из `bot` — DORMANT.
---

## 1. Назначение шага

Шаг обеспечивает обогащение метаданных рынка: по `market_id` (condition_id, который кит торговал) подтягивает из CLOB API человекочитаемое название рынка (`question`) и категорию (`tags` → нормализованная категория). Без этого шага сделки кита были бы видны только как hex-идентификаторы рынков, что делает невозможной читаемую отчётность (уведомления о paper-сделках, логи, аналитика).

Бизнес-смысл: «перевести» технический `condition_id` в человекочитаемые «название рынка» и «категория».

---

## 2. Статус

**CONFIRMED-ACTIVE** для основного канала (`PolymarketClient.get_market()` через cache-модули `market_title_cache.py` и `market_category_cache.py`) внутри сервиса `whale-detector`. Reachable consumers: `WhaleDetector.save_trade_to_db` (`whale_detector.py:536`), `RealTimeWhaleMonitor._on_trade_signal` (`real_time_whale_monitor.py:475, :517`), `WhalePoller._poll_whales` (`whale_poller.py:291`).

**DORMANT** для модулей сервиса `bot`: `VirtualBankroll` (`virtual_bankroll.py:668, :808`) и `CopyTradingEngine` (`copy_trading_engine.py:394`) импортируют cache-функции, но в Phase 2B инстанцирование закомментировано в `main.py`. По `PROJECT_STATE.md` оба модуля имеют статус FROZEN/disabled.

**SCRIPT-ONLY:** `category_backfill.py:112, :306` — standalone script, не сервис.

**DEAD CODE** для четырёх публичных методов клиента (`get_markets`, `get_orderbook`, `get_price`, `get_stats`): определения существуют, в production не вызываются.

**DEAD CODE / NOT-IMPLEMENTED** для метода `connect_websocket()`: метод выбрасывает `NotImplementedError`.

Дата верификации: 2026-05-10.

---

## 3. Исходные файлы

**Клиент (singleton-уровень):**
`src/execution/polymarket/client.py` — класс `PolymarketClient` (определение `client.py:67`). HTTP-библиотека: `aiohttp` (`client.py:20`). Класс хранит **три** базовых URL как class-level константы:

| Константа | Значение | Файл:строка |
|-----------|----------|-------------|
| `CLOB_API` | `https://clob.polymarket.com` | `client.py:79` |
| `GAMMA_API` | `https://gamma-api.polymarket.com` | `client.py:80` |
| `WS_URL` | `wss://ws-subscriptions-clob.polymarket.com/ws` | `client.py:81` |

**Cache-модули (фактические потребители):**

| Файл | Класс/функции | Singleton клиента | Используемый метод клиента |
|------|---------------|-------------------|----------------------------|
| `src/data/storage/market_title_cache.py` | `get_market_title(market_id)` | `_client = PolymarketClient()` (`market_title_cache.py:31`) | `client.get_market(market_id)` (`market_title_cache.py:71`) |
| `src/data/storage/market_category_cache.py` | `get_market_category(market_id)`, `get_market_category_with_title(market_id)` | `_client = PolymarketClient()` (`market_category_cache.py:84`) | `client.get_market(market_id)` (`market_category_cache.py:161`, `:222`) |

Импорты `PolymarketClient` в production: ровно два (`market_title_cache.py:19`, `market_category_cache.py:20`). Других production-импортов класса нет.

**Прямые `aiohttp`-обходы клиента к CLOB/Gamma API в коде проекта** (модули, обращающиеся к тем же эндпоинтам Polymarket помимо `PolymarketClient`):

| Файл:строка | Endpoint |
|-------------|----------|
| `run_whale_detection.py:64–68` | `gamma-api.polymarket.com/events` (прямой `session.get`) |
| `run_whale_detection.py:83–87` | `gamma-api.polymarket.com/markets` (прямой `session.get`) |
| `run_whale_detection.py:134` | `gamma-api.polymarket.com/markets` (fallback) |
| `roundtrip_builder.py:41` | константа `GAMMA_API = "https://gamma-api.polymarket.com"` |
| `whale_roundtrip_reconstructor.py:38` | константы `GAMMA_API`, `CLOB_API` |
| `paper_position_settlement.py:42` | константа `CLOB_API = "https://clob.polymarket.com"` |

Эти модули относятся к скоупу будущих шагов карты, но факт их существования — RED FLAG для шага 1B (см. §13). Обоснование наличия параллельных каналов в коде отсутствует: docstrings и комментарии не объясняют, почему `PolymarketClient` не используется этими модулями.

---

## 4. Контейнер

`PolymarketClient` **не имеет собственного docker-compose сервиса** — это библиотечный класс, экземпляры которого создаются как module-level singletons внутри cache-модулей. Cache-модули, в свою очередь, импортируются и вызываются production-модулями, работающими в двух сервисах:

| Сервис | Команда запуска | Какие production-модули в этом сервисе используют cache (и через них — `PolymarketClient`) |
|--------|------------------|----------------------------------------------------------------------------------------|
| `bot` | `python src/main.py` | `virtual_bankroll.py`, `copy_trading_engine.py` |
| `whale-detector` | `python src/run_whale_detection.py` | `whale_detector.py`, `real_time_whale_monitor.py`, `whale_poller.py` |

В активном `whale-detector`-процессе живёт **по одному** singleton'у `_client` на cache-модуль — итого 2 экземпляра `PolymarketClient` фактически работают в production, с независимыми sliding-window rate limiter'ами и независимыми in-memory кешами. Третий экземпляр (`category_backfill.py`) создаётся только при запуске script'а.
---

## 5. Триггер запуска и расписание

`PolymarketClient` не имеет собственного триггера и собственного расписания — он не работает по таймеру и не опрашивает API сам. Запросы инициируются только тогда, когда другой модуль обрабатывает новую сделку кита и хочет узнать название/категорию её рынка.

Ниже — основные циклы двух контейнеров, в которых сделки доходят до точки обращения за метаданными:

| Сервис / Модуль | Что делает в каждой итерации | Интервал sleep между итерациями | Файл:строка sleep |
|------------------|--------------------------------|---------------------------------|-------------------|
| `bot` (main service loop) | Один шаг основного цикла торгового бота | 1 сек | `main.py:387` |
| `whale-detector` (main loop) | Один шаг основного цикла обнаружения китов | 10 сек | `run_whale_detection.py:292` |
| `real_time_whale_monitor` (внутри `whale-detector`) | Один шаг real-time мониторинга сигналов | 1 сек | `real_time_whale_monitor.py:319` |
| `whale_poller.run_hot_polling` (внутри `whale-detector`) | Полный обход всех HOT-китов | 14 400 сек (4 ч) | `whale_poller.py:445–446` (`HOT_POLL_INTERVAL_SECONDS`, `whale_poller.py:42`) |
| `whale_poller.run_warm_polling` (внутри `whale-detector`) | Полный обход всех WARM-китов | 86 400 сек (24 ч) | `whale_poller.py:488–489` (`WARM_POLL_INTERVAL_SECONDS`, `whale_poller.py:43`) |

**Как часто реально происходят запросы к CLOB.** Не каждую секунду и не каждые 10 секунд. Запрос выполняется в одном из двух случаев:

1. Очередная итерация цикла принесла сделку по рынку, которого процесс ещё не видел — это первый запрос на этот `market_id`.
2. Та же сделка обрабатывается во втором cache-модуле (например, `whale_detector` сначала спросил у `market_title_cache`, потом у `market_category_cache`) — это второй запрос на тот же `market_id`.

Все последующие сделки по уже виденному рынку обслуживаются из локального dict-кеша без обращения к API.

**Время отклика для downstream-кода:**

- Для рынка, который уже встречался в этом процессе: ответ возвращается мгновенно из памяти (никакого сетевого вызова).
- Для нового рынка при работающем CLOB: один сетевой round-trip (по умолчанию доли секунды).
- Для нового рынка при сетевых ошибках без 429: до **93 секунд** (3 attempts × 30s timeout + linear backoff 1 + 2 сек). Всё это время downstream-вызов `await get_market_title(...)` блокирует обработку сделки.
- Для нового рынка при HTTP 429 с большим значением `Retry-After`: время ответа не ограничено сверху (см. §13 RED FLAG #6).

---

## 6. Алгоритм шага

### Что происходит на бизнес-уровне

Обработчик сделки (например, модуль обнаружения китов или модуль копирующей торговли) знает идентификатор рынка (`market_id`), на котором кит совершил сделку. Этот идентификатор — длинная hex-строка, по ней нельзя понять, о каком вопросе ставка («Победит ли X на выборах в Y?», «Превысит ли цена биткоина $Z к дате W?» и т.п.) и в какой категории этот рынок (политика / спорт / крипто / прочее).

Чтобы получить эти два человекочитаемых поля, обработчик обращается к локальному кешу. Кеш в первый раз отвечает «не знаю» — и в этот момент идёт запрос к публичному API Polymarket (CLOB) за документом метаданных рынка. Из ответа берутся только два поля: вопрос рынка (`question`) и его категория (`tags`, нормализуется на стороне клиента). Эти два значения сохраняются в локальной памяти процесса и сразу возвращаются обработчику. Все последующие сделки по тому же рынку в том же процессе будут обслужены из кеша без обращения к API.

### Технический алгоритм (один цикл обработки сделки)

1. Production-модуль (например, `whale_detector.py:530`) обрабатывает сделку с известным `market_id` (condition_id).
2. Вызывается `await get_market_title(market_id)` и/или `await get_market_category(market_id)`.
3. Cache-модуль проверяет `dict`, прицепленный как атрибут к функции (`get_market_title._cache.get(market_id)` — `market_title_cache.py:60–67`):
   - если запись есть **и не `None`** — возврат кешированного значения, шаг 1B завершён;
   - если записи нет — переход к API-вызову.
4. Cache-модуль получает singleton клиента через `_get_client()` (`market_title_cache.py:38`, `market_category_cache.py:65`).
5. Внутри `PolymarketClient.get_market(market_id)` (`client.py:269`):
   - формируется URL: `f"{self.CLOB_API}/markets/{market_id}"` (`client.py:278`);
   - вызывается `await self._make_request("GET", url)` (`client.py:279`).
6. Внутри `_make_request` (`client.py:160–245`):
   - вызов `await self._apply_rate_limit()` (`client.py:181`) — sliding window 100/60s;
   - получение/переиспользование сессии через `_get_session()` (`client.py:117–123`);
   - цикл `for attempt in range(self.max_retries)` (`client.py:197`):
     - `async with session.request("GET", url, headers=request_headers, timeout=ClientTimeout(total=30))` (`client.py:204`);
     - на HTTP 200 — `return await resp.json()`;
     - на HTTP 429 — `asyncio.sleep(retry_after)` и продолжение цикла;
     - на других не-200 — `raise PolymarketAPIError`;
     - на `aiohttp.ClientError` — log WARNING, linear backoff `retry_delay × (attempt+1)`.
7. Cache-модуль получает `Dict[str, Any]` (raw JSON), извлекает поле:
   - `market_title_cache`: `market_data.get("question")` (`market_title_cache.py:74`);
   - `market_category_cache`: `market_data.get("tags")` → `_normalize_category(tags)` (`market_category_cache.py:164`).
8. Результат сохраняется в локальный `_cache`-dict (включая `None` — см. §13 RED FLAG #11) и возвращается вызывающему модулю.

### Обработка дублей

Дедупликация в шаге 1B реализована **на уровне in-memory кеша** в каждом cache-модуле: повторные обращения к одному и тому же `market_id` в рамках одного процесса резолвятся из dict'а без обращения к API.

Особенности:
- Кеш **не разделяется** между cache-модулями (`title` и `category` имеют независимые dict'ы), поэтому первый вызов `get_market_title(X)` и первый вызов `get_market_category(X)` для одного `market_id` приводят к **двум** отдельным API-запросам с одинаковыми параметрами.
- Кеш **не разделяется** между процессами (`bot` и `whale-detector` имеют независимые in-memory dict'ы), поэтому первое появление `market_id` в каждом из четырёх `_cache`-словарей (2 cache-модуля × 2 контейнера) даёт API-запрос.
- При `Exception` от клиента в cache не пишется ничего (`market_title_cache.py:86–88`, `market_category_cache.py:194–200`) — повторный вызов снова пойдёт в API.
- При валидном ответе с `question is None` или `tags is None`/пустым — `None` **сохраняется** в кеш и закрепляется на всё время жизни процесса (см. §13 RED FLAG #11).

---

## 7. Формат входных данных

**На вход публичной функции cache-модуля:**
- `market_id: str` — condition_id рынка Polymarket, передаваемый production-модулем (значение приходит из downstream pipeline'а, в шаге 1B не нормализуется).

**На вход `PolymarketClient.get_market`:**
- `market_id: str` (`client.py:269`).

**Параметры HTTP-запроса:**
- HTTP-метод: `GET`
- URL: `https://clob.polymarket.com/markets/{market_id}` (path-параметр)
- Query parameters: отсутствуют
- Headers (`client.py:186–193`):
  - `Accept: application/json`
  - `Accept-Encoding: gzip, deflate` (явно без `br`/brotli — `client.py:188`)
  - `Authorization: Bearer <api_key>` — добавляется только при `self.api_key is not None`. В обоих cache-модулях клиент создаётся как `PolymarketClient()` без `api_key` (`market_title_cache.py:31`, `market_category_cache.py:84`), поэтому в production header отсутствует.

**Конструктор `PolymarketClient`:**
```
PolymarketClient(api_key: Optional[str] = None, max_retries: int = 3, retry_delay: float = 1.0)
```
(`client.py:87–92`). `settings`/env-переменные внутри `PolymarketClient.__init__` не читаются.

---

## 8. Формат выходных данных

API возвращает JSON-документ метаданных рынка. Клиент возвращает его как **сырой `Dict[str, Any]`** без преобразования в dataclass. Cache-модули используют `dict.get()` для извлечения нужных полей.

**Поля API → возврат cache-модуля:**

| Поле API | Cache-модуль | Преобразование | Возврат | Файл:строка |
|----------|--------------|-----------------|---------|-------------|
| `question` | `market_title_cache.get_market_title` | прямое чтение | `Optional[str]` | `market_title_cache.py:74` |
| `tags` | `market_category_cache.get_market_category` | `_normalize_category(tags)` (берёт первый элемент списка и маппит на нормализованную категорию) | `Optional[str]` | `market_category_cache.py:164` |
| `tags` + `question` | `market_category_cache.get_market_category_with_title` | оба поля одним вызовом | `tuple[Optional[str], Optional[str]]` (category, title) | `market_category_cache.py:228, :232` |

При отсутствии поля или значении `None`:
- `dict.get("question")` → `None` (без исключения);
- `dict.get("tags")` → `None` (без исключения);
- `_normalize_category(None)` или пустого списка → `None`.

Ни один из этих случаев не приводит к исключению — все `None`-значения сохраняются как negative cache (см. §6, «Обработка дублей»).

---

## 9. Записи в БД

**На самом шаге 1B прямой записи в БД нет.** Cache-модули используют исключительно **in-memory `dict`**, прицепленный как атрибут к публичной функции (`get_market_title._cache`, `get_market_category._cache` — `market_title_cache.py:67`, `market_category_cache.py:157`).

- Postgres / Redis / файловое хранилище: **не используются**.
- TTL / expiration: отсутствует.
- Persistence между рестартами процесса: отсутствует (in-memory by design — после рестарта контейнера кеш заполняется заново на cache-miss'ах).
- Ручная инвалидация: функции `clear_cache()` (`market_title_cache.py:91–95`, `market_category_cache.py:255–259`), на момент верификации не вызываются ни одним production-модулем.

Constraints / индексы / FK / idempotency: N/A (нет целевой БД-таблицы).

Запись метаданных рынков в Postgres-таблицу выполняется **другим** процессом — `category_backfill.py` (`src/data/storage/category_backfill.py`), который относится к скоупу отдельного шага карты (это утилитарный скрипт, не часть `bot`/`whale-detector` контейнеров — Roo подтвердил отсутствие compose-сервиса для него).

---

## 10. Условия успеха / частичного успеха / неуспеха

**Успех:** HTTP 200, JSON распарсен, поле `question` или `tags` извлечено (включая `None`), кеш обновлён, значение возвращено вызывающему модулю.

**Частичный успех:** HTTP 200, JSON распарсен, но запрошенное поле в ответе отсутствует или равно `None` — cache-модуль логирует WARNING (`market_title_not_found` — `market_title_cache.py:80`; `market_category_tags_not_found` — `market_category_cache.py:185`) и сохраняет `None` в кеш как валидное значение. Pipeline продолжает работу с `None`.

**Неуспех (для конкретного вызова):**
- HTTP 4xx/5xx (кроме 429) → `PolymarketAPIError(f"API error {status}: {body[:200]}")` (`client.py:227–229`); cache-модуль ловит как `Exception`, логирует ERROR, возвращает `None`, **в кеш ничего не пишет** (повторный вызов снова попробует API).
- HTTP 429 → `Retry-After` sleep, retry в том же for-loop (счётчик `attempt` уже инкрементирован — см. §13 RED FLAG #6).
- `aiohttp.ClientError` (включая сетевые ошибки и невалидный JSON на 200) → linear backoff `retry_delay × (attempt+1)`, после `max_retries=3` — `PolymarketAPIError`.
- Превышение 30s timeout → `aiohttp.ClientError` → стандартный retry-путь.

При неуспехе клиента контейнер не падает — cache-модуль изолирует исключение и возвращает `None`.

---

## 11. Зависимости

**Upstream:** внешний публичный сервис `https://clob.polymarket.com` (нет SLA от провайдера).

**Downstream consumers (production-модули, вызывающие cache-функции):**

| Cache-функция | Вызывающий модуль | Файл:строка вызова | Сервис |
|---------------|-------------------|---------------------|--------|
| `get_market_title` | `whale_detector.py` | `:536` | `whale-detector` |
| `get_market_title` | `real_time_whale_monitor.py` | `:475` | `whale-detector` |
| `get_market_title` | `virtual_bankroll.py` | `:668`, `:808` | `bot` |
| `get_market_title` | `copy_trading_engine.py` | `:394` | `bot` |
| `get_market_category` | `whale_poller.py` | `:291` | `whale-detector` |
| `get_market_category` | `real_time_whale_monitor.py` | `:517` | `whale-detector` |
| `get_market_category` | `category_backfill.py` | `:112`, `:306` | (utility script, не сервис) |

**SQL-зависимости:** N/A (см. §9).

**External services:** rate limits Polymarket CLOB API не задокументированы публично. Клиент применяет собственный sliding window 100 req/min/процесс.

**Other resilience-related dependencies:**
- `aiohttp` (`client.py:20`) — HTTP transport.
- `asyncio.Lock` для синхронизации rate limiter (`client.py:109`).
- `structlog` для логирования (`client.py:21–23`, оба cache-модуля).

---

## 12. Наблюдаемость

Логирование через `structlog`.

**Логи `PolymarketClient` (`client.py`):**

| Событие | Уровень | Структурированные ключи | Файл:строка |
|---------|---------|--------------------------|-------------|
| `polymarket_client_initialized` | INFO | `api_key_set`, `max_retries` | `client.py:111–115` |
| `polymarket_client_closed` | INFO | — | `client.py:129` |
| `rate_limit_hit` (клиентский) | WARNING | `wait_seconds`, `queued_requests` | `client.py:148–152` |
| `server_rate_limit` (HTTP 429) | WARNING | `retry_after`, `attempt` | `client.py:213–217` |
| `polymarket_api_error` (non-200/429) | ERROR | `status`, `url`, `error` | `client.py:221–226` |
| `request_failed` (`aiohttp.ClientError`) | WARNING | `error`, `attempt`, `max_retries` | `client.py:233–238` |

**Логи cache-модулей:**

| Событие | Уровень | Структурированные ключи | Файл:строка |
|---------|---------|--------------------------|-------------|
| `market_title_cache_hit` | DEBUG | `market_id` (truncated 20c) | `market_title_cache.py:64` |
| `market_title_fetched` | INFO | `market_id`, `title` (truncated 50c) | `market_title_cache.py:78` |
| `market_title_not_found` | WARNING | `market_id` | `market_title_cache.py:80` |
| `market_title_fetch_failed` | ERROR | `market_id`, `error` | `market_title_cache.py:87` |
| `market_title_cache_cleared` | INFO | — | `market_title_cache.py:95` |
| `market_category_cache_hit` | DEBUG | `market_id` | `market_category_cache.py:154` |
| `market_category_fetched` | INFO | `market_id`, `category`, `raw_tags[:3]` | `market_category_cache.py:170` |
| `market_category_normalization_failed` | WARNING | `market_id`, `tags` | `market_category_cache.py:177` |
| `market_category_tags_not_found` | WARNING | `market_id` | `market_category_cache.py:185` |
| `market_category_fetch_failed` | ERROR | `market_id`, `error` | `market_category_cache.py:195` |
| `category_unmapped` | WARNING | `primary_tag`, `all_tags` | `market_category_cache.py:124` |
| `market_category_cache_cleared` | INFO | — | `market_category_cache.py:259` |

**Метрики:** не обнаружены.
**Алерты на состояние CLOB API:** не обнаружены.
**Адреса/`market_id` частично редактируются** (truncate 20–50 символов) в части логов.

---

## 13. Особые случаи и риски

**RED FLAG #1 — Bypass-эпидемия CLOB/Gamma API.** `PolymarketClient` не используется как единая точка интеграции с Polymarket REST. В коде проекта присутствуют **минимум четыре** модуля с прямыми `aiohttp`-обращениями к тем же эндпоинтам: `run_whale_detection.py:64–87, :134` (3 прямых вызова к Gamma `/events` и `/markets`), `roundtrip_builder.py:41`, `whale_roundtrip_reconstructor.py:38`, `paper_position_settlement.py:42`. Обоснование (комментарии, docstrings, TODO) отсутствует. Следствие: разная обработка ошибок, разные таймауты, отсутствие общей точки контроля rate limit.

**RED FLAG #2 — `connect_websocket()` — `NotImplementedError` в публичном API.** Метод `PolymarketClient.connect_websocket()` (`client.py:347–355`) выбрасывает `NotImplementedError("WebSocket support not yet implemented. Use REST API methods for now.")`. Метод присутствует в публичной поверхности класса. WebSocket-функциональность реализована в **отдельном** классе `PolymarketWebSocket` (`src/data/ingestion/websocket_client.py`) — не описывается в шаге 1B.

**RED FLAG #3 — Dead constant `WS_URL` с отличающимся значением.** `PolymarketClient.WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws"` (`client.py:81`) не используется ни одним модулем. Рабочий WebSocket-канал в проекте (`PolymarketWebSocket.WS_URL`, `src/data/ingestion/websocket_client.py:30`) указывает на `wss://ws-subscriptions-clob.polymarket.com/ws/market` — путь отличается суффиксом `/market`. Значения двух одноимённых констант в проекте расходятся.

**RED FLAG #4 — Dead constant `GAMMA_API`.** `PolymarketClient.GAMMA_API = "https://gamma-api.polymarket.com"` (`client.py:80`) объявлена как class-level константа, но единственный используемый метод (`get_market`) обращается только к `CLOB_API`. Прочие методы класса, потенциально использующие `GAMMA_API` — DEAD CODE (см. RED FLAG #5).

**RED FLAG #5 — 4 из 5 публичных async-методов класса — DEAD CODE.** Подтверждённые отсутствия вызовов на инстансах `PolymarketClient` в production-коде: `get_markets()` (`client.py:247`), `get_orderbook()` (`client.py:289`), `get_price()` (`client.py:323`), `get_stats()` (`client.py:357`). Все одноимённые вызовы в коде проекта относятся к **другим** классам (`PolymarketDataClient`, `BuilderClient`, `WhaleDetector`, `VirtualBankroll`, `WhaleTradesRepo`). Используется только `get_market()`. 80% публичной поверхности класса — мёртвый код.

**RED FLAG #6 — HTTP 429 не инкрементирует ретраи отдельно от network errors.** В `_make_request` (`client.py:197–245`) цикл `for attempt in range(self.max_retries)` единый для всех ошибок. На HTTP 429 вызывается `asyncio.sleep(retry_after)`, после чего `attempt` продвигается на следующую итерацию (как и при `aiohttp.ClientError`). Это означает: бюджет `max_retries=3` единый для обоих типов ошибок и расходуется любым из них. Кроме того, фактическое значение из `Retry-After` не валидируется и не ограничивается сверху — клиент использует его буквально (`client.py:212`).

**RED FLAG #7 — JSON parse error на HTTP 200 расходует ретрай-бюджет.** Если CLOB вернёт 200 с битым JSON, `await resp.json()` бросит исключение, которое попадёт в общий `except aiohttp.ClientError` (`client.py:231–240`). Запрос будет повторён до 3 раз с linear backoff. Ошибка сериализации обрабатывается тем же путём, что и сетевые сбои. В `PolymarketDataClient` (шаг 1A, RED FLAG #6) тот же класс ошибки не отлавливается — `JSONDecodeError` улетает наверх. Между двумя клиентами одного проекта обработка JSON-ошибок реализована по-разному.

**RED FLAG #8 — `close()` никогда не вызывается.** Метод `PolymarketClient.close()` (`client.py:125–129`) — единственный механизм корректного завершения HTTP-сессии в классе. Roo подтвердил отсутствие вызовов `client.close()` или `await client.close()` из любого внешнего модуля в кодовой базе. Singleton'ы `_client` в cache-модулях создаются один раз и не закрываются явно — сессия `aiohttp.ClientSession` живёт до завершения процесса.

**RED FLAG #9 — In-memory cache без TTL и без верхнего предела размера.** Оба cache-модуля используют `dict`, прицепленный к функции (`get_market_title._cache`, `get_market_category._cache`). Отсутствуют: TTL на запись, max_size на dict, периодическая инвалидация. Каждый новый `market_id` добавляет запись на всё время жизни процесса. Метрики и алерты на размер кеша не обнаружены.

**RED FLAG #10 — Кеш не разделяется между cache-модулями и между контейнерами.** Для одного `market_id` существует **четыре** независимых dict-кеша (2 cache-модуля × 2 контейнера). Первый запрос на title и первый запрос на category по одному `market_id` дают **два** отдельных API-вызова к одному и тому же URL `/markets/{market_id}` (cache-модули не делят результат). Аналогично, процессы `bot` и `whale-detector` независимо запрашивают одни и те же `market_id`. Координация запросов между процессами и cache-модулями отсутствует.

**RED FLAG #11 — Negative caching на свежие рынки фиксируется до перезапуска процесса.** При получении валидного ответа с `question is None` или пустым/None `tags` cache-модули записывают `None` в кеш (`market_title_cache.py:81–82`, `market_category_cache.py:185–187`) и при последующих обращениях с тем же `market_id` возвращают этот `None` без повторного API-запроса. Если в момент первого обращения метаданные рынка ещё не были заполнены провайдером, `None` останется в кеше до перезапуска контейнера `whale-detector`. Механизм per-key инвалидации отсутствует (`clear_cache()` сбрасывает кеш целиком). На downstream-эффекты в текущем production'е: `None` попадёт в `whale_trades.market_title` через `WhaleTradesRepo.save_trade(market_title=...)`, после чего будет исправлен фоновым `category_backfill.py` (запуск через cron) — `None`-значение в кеше живёт до рестарта, но в БД может быть восстановлено backfill'ом.

**RED FLAG #12 — Cache-модули ловят `Exception`, не `PolymarketAPIError`.** В `try/except` обоих cache-модулей (`market_title_cache.py:86`, `market_category_cache.py:194`) перехватывается общий `Exception`. Это маскирует под «нет данных» любую программную ошибку (`AttributeError`, `KeyError`, `TypeError` от багов парсинга и т.д.), не только API-проблемы. Диагностика затруднена: ошибка попадает только в ERROR-лог `*_fetch_failed` без stack trace, наружу уходит `None`.

**RED FLAG #13 — `PolymarketAPIError` без structured fields.** Класс наследует `Exception` без дополнительных атрибутов (`client.py:375–378`). `status_code`, `url`, тело ответа — только в форматированной строке `args[0]`. Программно отличить «429 после 3 ретраев» от «500 без ретрая» можно только парсингом строки, что в cache-модулях не делается (см. RED FLAG #12).

**RED FLAG #14 — Linear backoff без jitter.** При сетевой ошибке backoff детерминирован: `retry_delay × (attempt+1)` = 1s, 2s, 3s (`client.py:240`). Случайный компонент (jitter) в формуле отсутствует. На текущем количестве процессов (4 экземпляра в production) эффект ограниченный; при горизонтальном масштабировании отсутствие jitter стандартно приводит к синхронным retry-всплескам.

**RED FLAG #15 — `_lru_cache` декоратор как параллельный артефакт кеширования.** В `market_title_cache.py:35` присутствует `_lru_cache` декоратор; одновременно фактическое кеширование выполняется через `_cache`-атрибут на самой функции (`market_title_cache.py:60–67`). В файле существуют два разных механизма с одним назначением. Источник путаницы для читающего код.

**RED FLAG #16 — Recursive `_apply_rate_limit()` без явного bound.** При исчерпании окна метод вызывает `await self._apply_rate_limit()` рекурсивно после `asyncio.sleep` (`client.py:155`). Глубина рекурсии формально не ограничена и зависит от того, сколько раз окно остаётся переполненным после очередного sleep'а. На текущем потолке 100 req/min глубина наблюдаемых рекурсий не измерялась.

**RED FLAG #17 — `Accept-Encoding` исключает brotli без документации.** В `_make_request` (`client.py:188`) явно задано `Accept-Encoding: gzip, deflate` (без `br`). Комментарий в коде указывает «explicitly excludes brotli» (`client.py:188` рядом со значением), причина решения в коде или docstring не зафиксирована.

**RED FLAG #18 — `api_key` параметр конструктора — фактически dead.** Все production-инстанциации создают `PolymarketClient()` без `api_key` (`market_title_cache.py:31`, `market_category_cache.py:84`). `Authorization` header в production не отправляется. Параметр и связанная с ним ветка кода (`client.py:191–193`) — DEAD CODE для текущего production'а.

---

## 14. Результат шага

После успешного выполнения:
- production-модуль (вызывающий cache-функцию) получает `Optional[str]` (название рынка) или `Optional[str]` (нормализованная категория) для своего `market_id`;
- запись помещена в локальный in-memory dict cache-модуля и будет переиспользована при следующих обращениях к тому же `market_id` в том же процессе;
- структурированные логи зафиксированы (cache hit / fetched / not_found / failed).

Без этого шага сделки кита невозможно отобразить в человекочитаемом виде в уведомлениях о paper-сделках, в логах и в downstream-аналитике (любые модули, ожидающие `market_title` или `market_category`).

---

## 15. Краткая бизнес-формула шага

```
production-модуль (whale_detector / virtual_bankroll / copy_trading_engine /
                  real_time_whale_monitor / whale_poller)
    обрабатывает сделку (market_id известен)
    │
    ├── await get_market_title(market_id) [market_title_cache.py]
    │   └── _cache hit? → return cached value
    │       _cache miss? ↓
    │           ├── PolymarketClient (singleton, без api_key)
    │           │   └── _apply_rate_limit() [sliding 100/60s]
    │           │       └── GET https://clob.polymarket.com/markets/{market_id}
    │           │           [retry: 429→Retry-After; ClientError→linear backoff×3;
    │           │            timeout 30s; non-200→PolymarketAPIError]
    │           ↓ Dict[str, Any]
    │           ├── market_data.get("question") → Optional[str]
    │           ├── _cache[market_id] = value (включая None)
    │           └── return value
    │
    └── await get_market_category(market_id) [market_category_cache.py]
        └── _cache hit? → return cached value
            _cache miss? ↓
                ├── PolymarketClient (singleton, независимый от title-cache)
                │   └── GET https://clob.polymarket.com/markets/{market_id}
                │       [тот же URL, второй HTTP-запрос]
                ↓ Dict[str, Any]
                ├── market_data.get("tags") → _normalize_category()
                ├── _cache[market_id] = value (включая None)
                └── return value

(Параллельные процессы `bot` и `whale-detector` имеют независимые
 singleton'ы PolymarketClient и независимые in-memory кеши.
 Один и тот же market_id может быть запрошен 4 раза с разных процессов/cache-модулей.)
```
