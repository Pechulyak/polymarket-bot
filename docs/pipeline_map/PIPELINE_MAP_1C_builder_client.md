# ШАГ 1C. ПОДКЛЮЧЕНИЕ К POLYMARKET CLOB BUILDER API (execution path)

## Краткая характеристика (TL;DR)

`BuilderClient` (`src/execution/polymarket/builder_client.py`) — **единственный** проектный канал размещения и отмены реальных ордеров на бирже Polymarket. Использует тот же хост `clob.polymarket.com`, что и `PolymarketClient` шага 1B, но с дополнительными authentication headers (3 ключа Builder API + приватный ключ кошелька для signing) и обращается к execution-эндпоинтам (`POST /order`, `DELETE /order/{id}`, `GET /order/{id}`, `GET /orders`).

**Шаг 1C полностью неактивен в текущем production (Phase 2B).** Цепочка `factory → BuilderClient → BuilderClientWrapper → CopyTradingEngine` физически отрезана от запускаемой docker-compose-топологии: factory `create_builder_client_from_settings()` ни разу не вызывается, `BuilderClient` нигде не создаётся напрямую, `BuilderClientWrapper` экспортируется из `__init__.py` но не инстанцируется. `CopyTradingEngine` (единственный потенциальный потребитель) импортируется только из `main_paper_trading.py`, который не упомянут как сервис в `docker-compose.yml`. Параллельный путь обхода клиента к execution endpoints CLOB **не обнаружен** — в этом единственная зона проекта без bypass-эпидемии.

Документ описывает заявленную архитектуру шага в облегчённом формате; детальная верификация CONTRACT/AUTH/ERRORS отложена до момента, когда будет принято решение о включении real execution.

## 1. Назначение шага

Шаг 1C должен обеспечить **запись** на блокчейн Polymarket: при срабатывании сигнала на копирование сделки кита (или иного триггера в будущей strategy-логике) клиент формирует и подписывает ордер, отправляет его на биржу CLOB через Builder API, получает подтверждение/отказ и возвращает результат downstream-коду. Шаг отличается от 1A (read-only data) и 1B (read-only metadata) тем, что **меняет состояние внешней системы** и **тратит средства**: каждое успешное размещение ордера приводит к фактическому исполнению на бирже Polymarket.

В текущем production (Phase 2B, paper trading) роль шага 1C — нулевая: ни одна реальная сделка не размещается, paper-исполнение реализовано **без обращения к CLOB** через DB-trigger `whale_trades → paper_trades` и downstream materialized views. Документация шага 1C нужна как pre-flight checklist для будущего включения real execution.

---

## 2. Статус

**INACTIVE / NOT WIRED IN PRODUCTION.**

Подтверждённые отсутствия в production-коде:
- `BuilderClient(...)` напрямую — ни один production-модуль не вызывает (только сама factory)
- `create_builder_client_from_settings()` — ни один production-модуль не вызывает
- `BuilderClientWrapper(...)` — ни один production-модуль не инстанцирует
- В активных entry points (`main.py`, `run_whale_detection.py`) импортов `BuilderClient`/wrapper/factory нет (импорт есть только в `copy_trading_engine.py:504` с маркировкой `# noqa: F401` — см. §13 RED FLAG #3)

Отдельный паттерн: подтверждено отсутствие параллельного `aiohttp`-обхода клиента к execution endpoints CLOB. Прямые вызовы `/order`, `/orders`, `/cancel` встречаются **только** внутри методов `BuilderClient`. Любая активация execution в будущем не наткнётся на конкурирующие точки записи.

Модули-потребители, на которые рассчитан клиент, FROZEN или dormant:
- `CopyTradingEngine` (`src/execution/copy_trading_engine.py`) — `PROJECT_STATE.md` статус `FROZEN, disabled`
- `main_paper_trading.py` (импортирует `CopyTradingEngine`) — не указан как сервис в `docker-compose.yml`

Дата верификации: 2026-05-10. Источники: 1C-INITIAL, 1C-CALLERS, 1C-BYPASS-CHECK отчёты Roo + `PROJECT_STATE.md` + `docker-compose.yml`.

---

## 3. Исходные файлы

**Клиент и связанная инфраструктура:**

| Файл | Класс / функция | Файл:строка |
|------|------------------|-------------|
| `src/execution/polymarket/builder_client.py` | `BuilderClient` | `builder_client.py:66` |
| `src/execution/polymarket/builder_client.py` | `BuilderClientWrapper` | `builder_client.py:490` |
| `src/execution/polymarket/builder_client.py` | `BuilderAPIError` (Exception) | `builder_client.py:35` |
| `src/execution/polymarket/builder_client.py` | `OrderResult` (dataclass) | `builder_client.py:41` |
| `src/execution/polymarket/builder_client.py` | `create_builder_client_from_settings()` (factory) | `builder_client.py:591` |
| `src/execution/polymarket/__init__.py` | Package-level exports `BuilderClient`, `BuilderClientWrapper`, `OrderResult`, `create_builder_client_from_settings` | `__init__.py:5–10` |

**Заявленный downstream-потребитель** (FROZEN, не активен):

| Файл | Класс / метод | Файл:строка | Статус |
|------|---------------|-------------|--------|
| `src/execution/copy_trading_engine.py` | `CopyTradingEngine._execute_live_trade` | `copy_trading_engine.py:483–553` | DORMANT — `CopyTradingEngine` импортируется только из `main_paper_trading.py`, который не запускается ни одним сервисом |
| `src/execution/copy_trading_engine.py` | `CopyTradingEngine._execute_paper_trade` | `copy_trading_engine.py:321–343` | DORMANT — тот же модуль |

**Прямые `aiohttp`-обходы клиента к execution endpoints CLOB:** не обнаружены. Все обращения к `/order` (POST), `/order/{id}` (DELETE/GET), `/orders` (GET) находятся внутри методов `BuilderClient` (`builder_client.py:364, :420, :440, :467`).

**База URL клиента:** `CLOB_API = "https://clob.polymarket.com"` (`builder_client.py:77`) — тот же хост, что и `PolymarketClient` шага 1B, но обращается к другим эндпоинтам и с дополнительной аутентификацией.

---

## 4. Контейнер

`BuilderClient` **не имеет собственного docker-compose сервиса** и **не работает в каком-либо активном сервисе** в Phase 2B.

Активные сервисы по `docker-compose.yml`:

| Сервис | Команда запуска | Использует BuilderClient? |
|--------|-----------------|---------------------------|
| `bot` | `python src/main.py --mode paper` | НЕТ — entry point `main.py` не импортирует `BuilderClient`, `BuilderClientWrapper`, factory, и не импортирует `CopyTradingEngine` |
| `whale-detector` | `python src/run_whale_detection.py` | НЕТ — read-only data ingestion и whale processing, без execution |
| `roundtrip_builder` | bash while-loop (sleep 7200) | НЕТ — settlement и aggregation `whale_trades`, без execution |

Точка, где `BuilderClient` мог бы быть подключён в будущем — `CopyTradingEngine.__init__` принимает опциональный параметр `builder_client`, но текущая активная топология не передаёт его никуда. Файл `main_paper_trading.py`, который умеет инстанцировать `CopyTradingEngine`, не запущен ни одним сервисом.

---

## 5. Триггер запуска и расписание

**Активного триггера нет.** Цепочка триггеров, заявленная в коде, имеет три уровня dormant-связей:

1. `create_builder_client_from_settings()` — factory ожидает вызова из downstream-кода. **Никто не вызывает.**
2. `CopyTradingEngine.__init__(builder_client=...)` — принимает клиент через DI. **Никто не передаёт**, потому что сам `CopyTradingEngine` не инстанцируется в активных сервисах.
3. `CopyTradingEngine._execute_live_trade(...)` — вызывает `self.builder_client.place_order(...)` при условии `if self.use_builder and self.builder_client`. Условие `self.use_builder` устанавливается в `__init__` как `builder_client is not None`. В текущем production'е `builder_client = None` по умолчанию (никто не передаёт), поэтому метод и не достигается.

Если когда-либо `BuilderClient` будет включён, расписание определится тем, как часто `CopyTradingEngine` будет получать торговые сигналы — по архитектуре это on-demand при срабатывании whale copy strategy. Конкретного расписания на уровне самого клиента нет; присутствуют атрибуты `_order_count_today` / `_order_count_reset` (см. §13 RED FLAG #6) — их точная роль не верифицирована.

Внутри `BuilderClient`:
- Конструктор с default `chain_id=137` (Polygon), `max_retries=3`, `retry_delay=1.0` — не вызывается
- `aiohttp.ClientSession` создаётся лениво — никогда не создаётся
- Authentication headers формируются через SDK или manual HMAC — never executed

---

## 6. Алгоритм шага (заявленный, не выполняется)

### Что должно происходить при активации

1. **Сигнал на торговлю.** Downstream-стратегия (например, `CopyTradingEngine`) принимает решение разместить ордер: определяет `market_id`, `side` (buy/sell), `size`, `price`.
2. **Проверка наличия клиента.** `if self.use_builder and self.builder_client` — если клиент сконфигурирован, идёт live-путь; иначе — fallback на `self.executor.execute(...)` (см. §13 RED FLAG #4) или возврат ошибки.
3. **Вызов `BuilderClient.place_order(...)`.** Клиент формирует HTTP-запрос с подписанными headers и отправляет POST на `https://clob.polymarket.com/order`.
4. **Обработка ответа.** На успех — возврат `OrderResult` с `order_id`, `filled`, `fill_price`. На ошибку — `BuilderAPIError`.
5. **Downstream-обработка.** `_execute_live_trade` извлекает поля `OrderResult` через attribute access (`.success`, `.order_id`, `.filled`, `.fill_price`, `.error`) и формирует dict для возврата.

### Authentication

Два альтернативных пути формирования headers (см. §13 RED FLAG #5):
- Через `py_builder_signing_sdk` (опциональный импорт, обёрнутый в `try/except ImportError`)
- Ручной HMAC-SHA256 fallback (`_generate_manual_headers`)

Выбор пути управляется флагом `self._use_sdk: bool` (`builder_client.py:136`), устанавливаемым в зависимости от наличия SDK во время импорта модуля.

### Обработка дублей

Реализация защиты от двойного размещения (idempotency через client order ID, retry-сценарий после network failure) **не верифицирована** — отложена до фазы детального описания. См. §13 пункты в сводной таблице.

---

## 7. Формат входных данных

`BuilderClient.place_order(market_id, side, size, price, ...)` — точные параметры, типы и валидация **не верифицированы**.

`BuilderClient.__init__` требует **четыре секретных параметра**:
- `api_key: str` — Builder API key
- `api_secret: str` — Builder API secret
- `passphrase: str` — Builder API passphrase
- `private_key: str` — приватный ключ кошелька для signing

Все четыре — required, без default-значений (`builder_client.py:80–89`). Также `chain_id: int = 137`, `max_retries: int = 3`, `retry_delay: float = 1.0`.

Источник credentials в production-сценарии — factory `create_builder_client_from_settings()`, читающая из `settings`-объекта снашённые имена в обоих регистрах:
- `builder_api_key` / `BUILDER_API_KEY`
- `builder_api_secret` / `BUILDER_API_SECRET`
- `builder_api_passphrase` / `BUILDER_PASSPHRASE`
- `polymarket_private_key` / `POLYMARKET_PRIVATE_KEY`

Factory возвращает `None` если хотя бы один из ключей отсутствует (`builder_client.py:630–641`).

Детализация request body, query params и signed headers — отложена.

---

## 8. Формат выходных данных

Заявленная структура — `OrderResult` dataclass (`builder_client.py:41`). Поля dataclass'а **не верифицированы целиком**; из 1C-BYPASS-CHECK §B известны атрибуты, к которым обращается `_execute_live_trade`:
- `.success: bool`
- `.order_id`
- `.filled`
- `.fill_price`
- `.error`

`OrderResult` экспортируется из `__init__.py`, но **не импортируется ни одним модулем-потребителем** (см. §13 RED FLAG #7) — `_execute_live_trade` извлекает поля через attribute access без type-hint.

`BuilderAPIError(Exception)` — класс ошибок (`builder_client.py:35`); внутреннюю структуру не верифицировали.

Детализация маппинга API-полей на `OrderResult.*` — отложена.

---

## 9. Записи в БД

В текущем production'е шаг 1C **не пишет в БД ничего**, так как ни один из его методов не вызывается.

Заявленная downstream-цепочка (если бы включили):
- `_execute_live_trade` возвращает dict вызывающему коду
- `CopyTradingEngine` принимает решение, что делать дальше — потенциально пишет в `trades` таблицу

Однако таблица `trades` в текущем production'е содержит только тестовые данные (`PROJECT_STATE.md` daily snapshots помечают: «trades table contains only virtual test trades»). Если real execution когда-либо будет включён, потребуется отдельный аудит всей цепочки записи: что пишется, в какие таблицы, какие constraints, как обеспечивается idempotency между попытками retry.

Constraints / индексы / FK / idempotency: **не верифицированы**, отложены.

---

## 10. Условия успеха / частичного успеха / неуспеха

В текущем production'е шаг 1C никогда не выполняется → условия неактуальны.

Заявленные исключения класса `BuilderAPIError` поднимаются в случае:
- Не-200 ответа от CLOB
- Сетевой ошибки после исчерпания `max_retries`
- (Прочие условия не верифицированы)

Детализация классов ошибок (HTTP 429, signature rejected, insufficient liquidity, slippage, и т.д.) — отложена.

---

## 11. Зависимости

**Upstream:** внешний публичный сервис `https://clob.polymarket.com` (тот же хост, что у шага 1B, но с дополнительной authentication).

**Downstream:** заявленный потребитель — `CopyTradingEngine` (FROZEN). Реальных активных потребителей в Phase 2B нет.

**External services:**
- `py_builder_signing_sdk` — опциональная Python-библиотека для подписи (импорт в `try/except ImportError`)
- При отсутствии SDK используется ручной HMAC-SHA256 без зависимости от внешних библиотек

**Cross-step dependencies:**
- Шаг 1B (`PolymarketClient`) использует тот же хост `clob.polymarket.com`. Координации rate limit между двумя клиентами на уровне приложения нет (см. §13 сводную таблицу).

**SQL-зависимости:** N/A в текущем состоянии (нет вызовов).

---

## 12. Наблюдаемость

В текущем production'е логов от `BuilderClient` нет — клиент не инстанцируется, его внутренние `logger.info` / `logger.warning` / `logger.error` события не возникают.

Заявленные логи `BuilderClient` (детальная структура — отложена):
- Инициализация клиента (с булевыми флагами наличия credentials, без значений)
- Размещение / отмена ордера
- Server rate limit (HTTP 429)
- API errors (non-200/non-429)

Метрики, алерты, трейсинг — не верифицированы.

---

## 13. Особые случаи и риски

Раздел приоритезирован: главные RED FLAG'и описаны полно, остальные observation сведены в финальную таблицу для проверки перед активацией.

### Главные риски

**RED FLAG #1 — Полная цепочка execution dormant с тройным разрывом.** Ни factory, ни клиент, ни wrapper, ни enclosing engine не подключены к запускаемой топологии. Активация требует трёх независимых изменений:

1. Вызов `create_builder_client_from_settings()` где-то в активном entry point — на текущий момент таких вызовов **ноль** в production-коде.
2. Передача результата factory в конструктор `CopyTradingEngine(builder_client=...)` — на текущий момент `CopyTradingEngine` сам не инстанцируется ни в одном активном сервисе (`PROJECT_STATE.md`: `copy_trading_engine.py` имеет статус FROZEN).
3. Подключение `main_paper_trading.py` (или иного запускающего модуля) как сервиса в `docker-compose.yml` — на текущий момент его там нет.

С точки зрения безопасности тройной разрыв означает, что включение execution требует осознанного многошагового изменения в трёх разных местах кодовой базы и docker-compose-конфигурации. С точки зрения documentation lag — каждое из трёх dormant-звеньев имеет свою историю и причину заморозки, не задокументированную в одном месте.

**RED FLAG #2 — Bypass-эпидемия отсутствует, но по причине dormant-статуса.** В шагах 1A и 1B мы зафиксировали системную проблему — несколько модулей шлют прямые `aiohttp`-вызовы к Gamma/CLOB read endpoints помимо клиентов. В шаге 1C bypass-эпидемии нет: единственная точка обращения к execution endpoints — методы `BuilderClient`. **Однако** этот «положительный результат» получен в условиях, когда execution-канал в принципе не работает. При будущей активации необходимо повторить bypass-проверку — по мере того, как разработчики будут подключать `BuilderClient` к downstream-логике, есть риск воспроизведения паттерна 1A/1B (сделать прямой `aiohttp.post(...)` к `/order` ради скорости/упрощения).

**RED FLAG #3 — `# noqa: F401` импорт `BuilderClient` в `_execute_live_trade` как dead import с маскировкой.** В `copy_trading_engine.py:504` присутствует `from execution.polymarket.builder_client import BuilderClient  # noqa: F401`, расположенный **внутри тела метода**. Сам метод использует не импортированный класс, а атрибут `self.builder_client` (`copy_trading_engine.py:507`). Маркер `# noqa: F401` подавляет linter warning «imported but unused», что делает мёртвый импорт неотличимым от намеренной заглушки. Возможные интерпретации:

- Артефакт незавершённого рефакторинга (импорт класса для будущего `isinstance`-проверки или type-hint, который так и не написали)
- Намеренный «маркер использования» для статического анализа dependency graph
- Ошибка при code review (`F401` поставили вместо удаления импорта)

В любой интерпретации: импорт не несёт функциональной нагрузки и подлежит удалению либо документированию причины. Рекомендация на момент активации: проверить и привести в порядок.

**RED FLAG #4 — Двухуровневый fallback в `_execute_live_trade` с непроверенной верхней зависимостью.** Метод реализует следующий fallback (`copy_trading_engine.py:483–553`):

```
self.builder_client.place_order(...)
   ↓ exception
self.executor.execute(...)
   ↓ self.executor is None
return {"success": False, "error": "No executor configured"}
```

Атрибут `self.executor` — это **второй** инжектируемый исполнитель, не идентичный `self.builder_client`. Что это такое (REST-клиент? wrapper? mock?), где и как он назначается в `CopyTradingEngine.__init__` — **в текущем анализе не верифицировано**. На момент активации необходимо отдельно установить:

1. Что `self.executor` — какой класс/интерфейс
2. Кто его настраивает (через DI? через factory? через None по умолчанию?)
3. Имеет ли он доступ к тем же credentials, что и `BuilderClient`, или работает иначе
4. Совпадает ли его error-handling с тем, что ожидает `_execute_live_trade`

Если `self.executor` тоже окажется dormant или вообще не существующим в production — fallback-ветка превратится в безмолвный `return {"success": False}` для **любой** ошибки `BuilderClient`, что эквивалентно потере торгового сигнала без видимого алерта.

**RED FLAG #5 — Два независимых пути аутентификации без документированного критерия выбора и без верификации эквивалентности.** Клиент содержит:

- Путь через `py_builder_signing_sdk` — опциональный импорт в `try/except ImportError` (`builder_client.py:127`)
- Ручной HMAC-SHA256 fallback (`_generate_manual_headers`)

Выбор пути управляется флагом `self._use_sdk: bool` (`builder_client.py:136`). Критерий — наличие SDK на момент импорта модуля. **Не верифицировано:**

1. Производят ли SDK и manual fallback **идентичные** signed headers для одного и того же набора `(api_key, secret, passphrase, private_key, payload)` 
2. Что произойдёт, если в production развёрнут контейнер без SDK, и manual-путь имеет несовместимый формат подписи — Polymarket вернёт `signature rejected`
3. Если SDK обновится и поменяет nonce-стратегию или payload-формат, manual-fallback может разойтись с ним молча

При активации необходимо: либо удалить один из путей, либо написать тесты, доказывающие эквивалентность подписи на репрезентативном наборе входов.

**RED FLAG #6 — Иной механизм учёта ордеров, чем у `PolymarketClient` шага 1B.** В отличие от `PolymarketClient` шага 1B, который использует sliding window 100 req/min (`_request_times` + `_rate_limit_lock`), `BuilderClient` хранит атрибуты `_order_count_today` и `_order_count_reset` (`builder_client.py:110–111`). Roo классифицировал их как `state`-атрибуты; точная роль (rate limiting? quota tracking? logging counter?) и алгоритм работы **не верифицированы** в текущем анализе. Если это rate-limiting механизм с дневным окном — он принципиально отличается от подхода шага 1B, и при будущем включении execution два клиента, бьющие один и тот же хост `clob.polymarket.com`, будут использовать **разные** модели ограничения частоты запросов без общего лимитера.

При активации: верифицировать точную роль `_order_count_today` / `_order_count_reset`, оценить публичные rate-limit'ы Polymarket Builder API и их соответствие выбранной механике.

**RED FLAG #7 — Plain-text приватный ключ как instance attribute.** `self.private_key` (`builder_client.py:104`) хранит приватный ключ кошелька как обычную Python-строку без обёртки в специальный secret-тип и без шифрования при хранении в памяти процесса.

Что **не верифицировано** в текущем анализе и подлежит проверке при активации:

1. Не попадает ли `self.private_key` в structured-логи (`logger.info(..., private_key=self.private_key)` или подобное)
2. Не выводится ли он в `__repr__` / `__str__` `BuilderClient`
3. Не сериализуется ли он в `BuilderAPIError.args[0]` при формировании error message
4. Не попадает ли он в Sentry events или другие external monitoring

На момент верификации Roo подтвердил один безопасный лог — `bool(private_key)` без значения (`builder_client.py:119–121`). Полный аудит не проводился.

### Прочие observation, требующие проверки при активации

| # | Observation | Файл:строка | Severity |
|---|-------------|-------------|----------|
| O1 | `BuilderClientWrapper` экспортируется из `__init__.py:5–10`, но не инстанцируется ни одним production-модулем — fallback-pattern определён, но не используется | `builder_client.py:490`, `__init__.py:5–10` | Low |
| O2 | `OrderResult` dataclass не импортируется ни одним модулем вне `builder_client.py`; downstream `_execute_live_trade` извлекает поля через attribute access без type-hint — потеря типизации | `builder_client.py:41`, `copy_trading_engine.py:507` | Low |
| O3 | Дублирующее чтение конфига (snake_case + SCREAMING_SNAKE_CASE) в factory без документации | `builder_client.py:617–627` | Low |
| O4 | `chain_id=137` (Polygon) hardcoded как default в конструкторе без проверки соответствия адресу кошелька (риск: подпись с неверным `chain_id` будет отклонена сетью) | `builder_client.py:85, :105` | Medium |
| O5 | `_session` и retry-логика: те же паттерны, что в 1B (`close()` никогда не вызывается, `aiohttp.ClientError` ловит JSON parse errors), но не верифицированы для `BuilderClient` отдельно | `builder_client.py:109` (session attribute) | Medium |
| O6 | Поведение rate limiting при активации одновременно `PolymarketClient` (1B) и `BuilderClient` (1C) — оба бьют `clob.polymarket.com` без общего лимитера | cross-step | Medium |
| O7 | Зависимость от `py_builder_signing_sdk` как опциональной библиотеки — не указана в `requirements.txt` явно (не верифицировано) | `builder_client.py:127` | Low |
| O8 | Test coverage для `BuilderClient` методов — не верифицирован; при включении real execution критично иметь покрытие edge cases (network failure mid-signing, idempotency после retry, signature mismatch) | tests/ | Medium |
| O9 | Idempotency через client order ID или эквивалент — не верифицировано; критично для retry-сценариев на сетевых ошибках, чтобы избежать двойного размещения ордера | `builder_client.py:place_order` | High при активации |
| O10 | `chain_id` валидация при `__init__` (нет проверки соответствия `private_key` сети) | `builder_client.py:80–107` | Medium |

---

## 14. Результат шага

В текущем production'е шаг 1C никогда не выполняется → результата нет. Downstream-консумеры (которые тоже dormant) не получают и не ожидают `OrderResult` от `BuilderClient`.

При гипотетической активации заявленный результат — `Dict[str, Any]` от `_execute_live_trade`, содержащий поля успеха/ошибки и идентификаторы размещённого ордера. Точная структура и downstream-обработка — отложены.

Без активации шага 1C и подключения downstream execution-логики проект остаётся в режиме paper trading: реальных ордеров не размещается, реальной экспозиции нет, реальные средства не задействованы.

---

## 15. Краткая бизнес-формула шага

```
[не выполняется в Phase 2B]

Заявленная формула при активации:

trading signal (CopyTradingEngine или иной triggering layer)
    │
    ├── if self.use_builder and self.builder_client:
    │   └── BuilderClient.place_order(market_id, side, size, price)
    │       ├── [внутренний rate-limit / order tracking — механика не верифицирована]
    │       ├── формирование headers:
    │       │   └── self._use_sdk ? py_builder_signing_sdk : _generate_manual_headers()
    │       └── POST https://clob.polymarket.com/order
    │           ├── HTTP 200: return OrderResult(success=True, ...)
    │           └── HTTP non-200 / network error: raise BuilderAPIError
    │
    └── else (или после exception от builder_client):
        └── self.executor.execute(...)
            └── self.executor is None: return {"success": False, "error": "No executor configured"}
```

**Текущая реальность:** ни один из этих путей не активен. Paper-сделки в production создаются полностью отдельной механикой — DB-trigger `whale_trades → paper_trades` без участия Python execution layer.