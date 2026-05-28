# PIPELINE_MAP_8 — `NotificationWorker` (paper-ветка P2)

**Статус документа:** ACTIVE-DEGRADED
**Дата верификации:** 2026-05-27
**Эталон формата:** `PIPELINE_MAP_7_paper_trigger.md`

---

## TL;DR

Второй шаг paper-ветки. Asyncio-worker `NotificationWorker` запущен как background task в контейнере `polymarket_bot`. Каждые 2 секунды опрашивает таблицу `paper_trade_notifications` и для каждой новой записи отправляет Telegram-уведомление о paper-сделке. После успешной отправки помечает запись как обработанную; failure → rollback и бесконечный retry в следующем цикле (нет счётчика попыток). Текущее состояние — **деградированное**: worker работает физически, но upstream-источник данных (`trigger_notify_paper_trade`) удалён из БД, таблица пуста, уведомления о новых paper-сделках в production не отправляются. Вероятно понадобится восстановить.

---

## 1. Назначение шага

Бизнес-смысл: оповещать оператора в Telegram о каждой новой paper-сделке в реальном времени (задержка ~2 секунды). Шаг 8 — единственная точка интеграции paper-ветки с внешним каналом. Отказ шага 8 не блокирует ни paper-сделки (шаг 7), ни расчёт P&L (шаг 9), но лишает оператора оперативной информации о происходящем.

---

## 2. Статус

**ACTIVE-DEGRADED** на 2026-05-27. Worker запущен и работает, но не выполняет полезной работы из-за разрыва upstream-цепочки.

| Уровень | Проверка | Результат |
|---|---|---|
| Процесс | Лог `notification_worker_started` от 2026-04-11, heartbeat обновляется | worker активен |
| Код | `src/monitoring/notification_worker.py`, инициализация в `src/main.py:167` | присутствует |
| Контейнер | `polymarket_bot` (docker-compose service `bot`), restart `unless-stopped` | работает |
| Upstream trigger | `SELECT tgname FROM pg_trigger WHERE tgname='trigger_notify_paper_trade'` | 0 rows — **отсутствует** |
| Таблица данных | `SELECT COUNT(*) FROM paper_trade_notifications` | 0 строк |
| Активность за час | docker logs grep notification | 0 событий обработки |

---

## 3. Где живёт

| Элемент | Путь |
|---|---|
| Код worker'а | `src/monitoring/notification_worker.py` |
| Класс | `NotificationWorker` |
| Инициализация | `src/main.py:167` (`NotificationWorker(database_url=..., poll_interval=2.0)`) |
| Запуск | `src/main.py`, `asyncio.create_task(notification_worker.start())` |
| Telegram-клиент | кастомный `TelegramAlerts` (aiohttp, **не** python-telegram-bot) |
| Upstream-источник (отсутствует) | `trigger_notify_paper_trade` из `scripts/add_telegram_notifications.sql` |
| DROP-скрипт | `scripts/disable_notifications.sql` |
| Read-источник | `paper_trade_notifications` |
| Write-цель | `paper_trade_notifications.notified` (UPDATE) + Telegram chat 946830266 |

---

## 4. Контейнер

`polymarket_bot` (docker-compose service `bot`). Запуск: `python src/main.py --mode paper`, restart policy `unless-stopped`. Worker — asyncio background task внутри main loop, не отдельный процесс. Тот же контейнер содержит heartbeat-цикл main.py (Phase 2B) и другую отключённую логику; шаг 8 — единственный активный функциональный компонент main.py в текущем состоянии.

---

## 5. Триггер запуска

**Однократный** — при старте `main.py`. Worker создаётся как объект, его `start()` запускается через `asyncio.create_task()` и работает до завершения процесса. Внутри `start()` — бесконечный цикл `while True` с `sleep(poll_interval)` между итерациями.

Условие активации: `if not observation_mode` (читается из env `OBSERVATION_MODE`). При `OBSERVATION_MODE=true` worker не стартует. В production по факту worker активен — `OBSERVATION_MODE` не выставлен в `true`.

Никаких внешних триггеров (cron, signal, webhook) нет. Перезапуск worker'а — только через перезапуск контейнера.

---

## 6. Алгоритм

Цикл polling из 5 пунктов, выполняется каждые `poll_interval = 2.0` секунды.

**Пункт 1 — Polling-запрос.**
SELECT всех колонок из `paper_trade_notifications` WHERE `notified = FALSE` ORDER BY `created_at ASC` LIMIT 10. Сортировка обеспечивает FIFO-доставку при наличии нескольких pending-записей. LIMIT защищает от burst'а (если бы в таблице появилось 10000 записей разом, worker не подвиснет).

**Пункт 2 — Early return при пустом результате.**
Если запрос вернул 0 строк — немедленный `return` из обработчика батча, далее `sleep(poll_interval)` и следующая итерация. В текущем deg-состоянии — всегда этот путь.

**Пункт 3 — Форматирование Telegram-сообщения.**
Для каждой записи в батче формируется сообщение в Markdown с эмодзи (🟢 для buy, 🔴 для sell, ⚡ как маркер, 📚 для контекста). Поля: сокращённый `whale_address` (`0x...abcd`, 6+4 символа), `market_title`, `side`, `outcome`, `price`, `size_usd`, `kelly_size`, `kelly_fraction`, `created_at`.

**Пункт 4 — Отправка через TelegramAlerts.**
HTTP POST через aiohttp на Telegram Bot API. `bot_token` из env `TELEGRAM_ALERT_BOT_TOKEN`, `chat_id` из env `TELEGRAM_CHAT_ID=946830266` (один chat).

**Пункт 5 — UPDATE notified=TRUE или rollback.**
При успешной отправке — `UPDATE paper_trade_notifications SET notified=TRUE WHERE id=...` + commit. При failure (network, Telegram API error, timeout) — rollback (commit не выполняется, `notified` остаётся `FALSE`). Запись будет повторно подхвачена в следующем polling-цикле через 2 секунды и так бесконечно (см. §13 RF1).

---

## 7. Формат входных данных

Worker не принимает аргументов снаружи (кроме `database_url` и `poll_interval` в конструкторе). Единственный входной канал — таблица `paper_trade_notifications`. Колонки, которые worker реально читает (все):

| Колонка | Тип | Назначение в worker'е |
|---|---|---|
| `id` | integer NOT NULL | для UPDATE notified |
| `paper_trade_id` | integer NOT NULL | для контекста (в сообщении не отображается) |
| `whale_address` | text NOT NULL | сокращается до 6+4 в сообщении |
| `market_id` | text NOT NULL | для отладки |
| `market_title` | text | основной идентификатор рынка для оператора |
| `side` | text NOT NULL | эмодзи 🟢/🔴 |
| `outcome` | varchar(50) | YES/NO в сообщении |
| `price` | numeric NOT NULL | в сообщении |
| `size_usd` | numeric | в сообщении |
| `kelly_fraction` | numeric | в сообщении |
| `kelly_size` | numeric | в сообщении |
| `created_at` | timestamp NOT NULL | в сообщении + ORDER BY |
| `notified` | boolean default FALSE | WHERE-фильтр |
| `source` | varchar(20) | контекст |
| `size` | numeric NOT NULL | в сообщении (shares) |

---

## 8. Формат выходных данных

### Прямой выход — Telegram-сообщение

Markdown-форматированное сообщение в chat 946830266 на каждую обработанную запись. Один запрос на одну запись (не batch в одном сообщении — батч из 10 даёт 10 отдельных Telegram-сообщений).

### Косвенный выход — UPDATE notified

`UPDATE paper_trade_notifications SET notified=TRUE WHERE id=<id>` после успешной отправки. Записи с `notified=TRUE` исключаются из следующих polling-запросов.

### Side-effect — отсутствие записи

Worker не пишет логи отправок в БД (нет audit-таблицы). Факт отправки наблюдается только через логи контейнера (`logger.info("notification_sent ...")`) и факт отображения в Telegram-чате.

---

## 9. Записи в БД

Шаг 8 пишет **в одну таблицу и одну колонку** — `paper_trade_notifications.notified` (UPDATE с `FALSE` на `TRUE`). Никаких INSERT, никаких записей в другие таблицы.

### Структура paper_trade_notifications

| Колонка | Тип | NULL | Default |
|---|---|---|---|
| `id` | integer | NO | autoincrement |
| `paper_trade_id` | integer | NO | — |
| `whale_address` | text | NO | — |
| `market_id` | text | NO | — |
| `side` | text | NO | — |
| `price` | numeric(20,8) | NO | — |
| `size` | numeric(20,8) | NO | — |
| `size_usd` | numeric(20,8) | YES | — |
| `kelly_fraction` | numeric(10,8) | YES | — |
| `kelly_size` | numeric(20,8) | YES | — |
| `source` | varchar(20) | YES | `'unknown'` |
| `created_at` | timestamp | NO | `now()` |
| `notified` | boolean | YES | `FALSE` |
| `market_title` | text | YES | — |
| `outcome` | varchar(50) | YES | — |

**Foreign keys: отсутствуют.** В частности — нет FK `paper_trade_id → paper_trades(id)`. Это критично для сценария re-create trigger'а (см. §13 RF3).

---

## 10. Условия успеха / частичного успеха / неуспеха

### Per-record

| Исход | Условие | Поведение |
|---|---|---|
| **Полный успех** | Telegram OK + UPDATE commit OK | `notified=TRUE`, запись выпадает из polling |
| **Telegram failure** | network/timeout/4xx/5xx от API | rollback, `notified=FALSE`, retry через 2с (бесконечно) |
| **БД failure при UPDATE** | потеря соединения, deadlock | rollback, `notified=FALSE`, retry; **возможно дублирование Telegram-сообщения**, если отправка прошла а UPDATE упал |
| **Worker crash** | exception, не пойманный | task завершается, восстановление только через перезапуск контейнера (`unless-stopped` поможет, если упадёт весь процесс) |

### Per-batch

Батч из 10 обрабатывается последовательно. Failure одной записи не прерывает обработку остальных (rollback per-record, не per-batch). При полном backlog'е в N записей время обработки ≈ `N × (Telegram RTT + БД RTT)`, что при N=10 и RTT~200мс ≈ 2с — близко к poll_interval. При N >> 10 worker догоняет порциями.

### Текущее (deg) состояние

Все polling-итерации возвращают 0 строк → early return → sleep. Никаких per-record исходов не случается, worker идёт по «холодному» пути.

---

## 11. Зависимости

### Upstream (отсутствует)

**`trigger_notify_paper_trade`** — должен был бы AFTER INSERT ON `paper_trades` копировать NEW в `paper_trade_notifications`. В БД отсутствует с неизвестной даты (DROP через `scripts/disable_notifications.sql` вне git). Без trigger'а `paper_trade_notifications` не пополняется ничем (нет других writer'ов).

### Upstream (если бы trigger существовал)

**Шаг 7** — INSERT в `paper_trades` активировал бы `trigger_notify_paper_trade`, который синхронно создал бы запись в `paper_trade_notifications`. Цепочка `шаг 7 → trigger_notify → paper_trade_notifications → worker → Telegram`.

### Downstream

**Telegram chat 946830266** — единственный конечный потребитель. Записи в `paper_trade_notifications` с `notified=TRUE` не читаются никем — это де-факто audit-trail без активных потребителей.

### External

| Сервис | Через что | Авторизация |
|---|---|---|
| Telegram Bot API | aiohttp HTTP POST | `TELEGRAM_ALERT_BOT_TOKEN` (env) |
| PostgreSQL | asyncpg/psycopg connection pool | `DATABASE_URL` (env) |

---

## 12. Метрики и мониторинг

- **Логи контейнера** — `notification_worker_started` при старте, `notification_sent` (одна строка на успешную отправку), exception traceback при failure. В текущем deg-состоянии за час 0 строк с `notification`.
- **БД-метрики**: `SELECT COUNT(*) WHERE notified=FALSE` — backlog size, сейчас 0.
- **Heartbeat**: косвенно через факт обновления контейнером файлов/логов; отдельного heartbeat-эндпоинта нет.
- **Отсутствует**: алерт «worker мёртв», «backlog растёт», «Telegram-отправка стабильно фейлится». Любое из этих состояний оператор увидит только через ручной audit.

---

## 13. RED FLAGs

### RF1 — Бесконечный retry без счётчика и backoff

При любой failure отправки в Telegram запись остаётся `notified=FALSE` и будет повторно обработана через `poll_interval=2с`. Нет колонки `retry_count`, нет exponential backoff, нет DLQ. Если Telegram API недоступен или токен невалиден — worker зацикливается на одной записи (батч из 10 будет 10 раз падать на каждой итерации), безуспешно повторяя каждые 2 секунды. В Telegram-чат при восстановлении сервиса может прийти лавина дубликатов (если часть отправок проходила, а UPDATE падал отдельно).

### RF2 — Возможное дублирование Telegram-сообщений

Отправка в Telegram и UPDATE в БД — **разные операции**, не атомарны. Сценарий: Telegram-отправка прошла успешно (HTTP 200 от API, сообщение в чате уже видно), но `UPDATE notified=TRUE` падает (потеря соединения с БД, deadlock). Rollback оставляет `notified=FALSE`, следующий цикл отправит сообщение ещё раз. Дубликат в чате гарантирован при таком сценарии. Защита (idempotency key, two-phase commit, проверка перед отправкой) отсутствует.

### RF3 — Отсутствие FK `paper_trade_id → paper_trades(id)` и стратегия восстановления

При гипотетическом re-create `trigger_notify_paper_trade` (восстановление уведомлений в production) trigger будет создавать записи **только для новых** INSERT в `paper_trades`, начиная с момента re-create. Все существующие записи в `paper_trades` (на 2026-05-27 — все paper-сделки, созданные после удаления trigger'а) **не будут уведомлены** — это не backfill-trigger. Если требуется уведомить о прошедших paper-сделках — нужен отдельный backfill-скрипт по аналогии с другими процессами восстановления в системе (например, sentinel-method из TRD-443 для roundtrip-ов: одноразовый INSERT с маркером MANUAL_BACKFILL для отличия от обычных записей). Также: orphaned записи в `paper_trade_notifications` (если бы они были) не отлавливаются БД при удалении из `paper_trades` — нет FK.

### RF4 — Worker крутится вхолостую, потребляя БД-ресурсы

Каждые 2 секунды — SELECT-запрос с условием `notified=FALSE`. Покрывающий индекс на этой колонке не верифицирован (в Q5 индексы не перечислены — нужно отдельно проверить). При full scan на пустой таблице нагрузка минимальна, но при росте `paper_trade_notifications` без trigger'а (например, при гипотетическом ручном INSERT для теста) деградация запроса возможна. Сейчас — холостые SELECT'ы 43200 раз в сутки.

### RF5 — История поломки не зафиксирована в git

`scripts/disable_notifications.sql` был выполнен вне git (commit-история скрипта существует, но факт его применения к prod БД не attached к коммиту). Точная дата и причина DROP'а неизвестны. Для будущего восстановления — отсутствует контекст «почему отключили» (rollback миграции, отладка, осознанное решение?).

### RF6 — Worker не уведомляет оператора о собственной деградации

В текущем состоянии оператор не знает, что уведомлений нет — нет алерта «backlog=0 уже месяц». Worker логирует только при наличии работы. Отказ цепочки «бесшумный» — единственный способ обнаружить, что цепочка сломана, — заметить отсутствие сообщений в Telegram (что требует знания, сколько их должно быть).

### RF7 — Один Telegram chat для всех уведомлений

`chat_id=946830266` — единственный destination. При смене оператора, при необходимости отдельных каналов для paper vs governance vs alerts — потребуется доработка кода (либо параметризация через env, либо routing per-notification-type).

### RF8 — Индекс на `paper_trade_notifications(notified)` не верифицирован

Покрывающий индекс на колонке `notified` или partial `WHERE notified=FALSE` не подтверждён инвентарём. На пустой таблице (текущее состояние) нагрузка от polling'а минимальна. При восстановлении upstream и накоплении записей в таблице без подходящего индекса — full scan каждые 2 секунды, деградация SELECT'а пропорционально росту таблицы. Релевантно для скоупа восстановления (см. RF3).

---

## 14. Связь со следующим шагом paper-ветки

**Следующий шаг paper-ветки — шаг 9** (`paper_simulation_pnl`, `paper_portfolio_state`, `whale_pnl_summary` materialized views). Связь — **отсутствует**: шаг 8 не пишет в `paper_trades`, не модифицирует `whale_trade_roundtrips`, не вызывает refresh. Шаг 9 работает независимо от шага 8 — даже при полностью неработающих уведомлениях P&L paper-портфеля рассчитывается корректно.

Шаг 8 — **конечная точка** одной ветви paper-цепочки (информирование оператора). Шаг 9 — **конечная точка** другой ветви (расчёт финансовых метрик). Они не зависят друг от друга и не имеют общих writes.

---

## 15. Краткая бизнес-формула шага

```
ВХОД: paper_trade_notifications.notified=FALSE записи (FIFO по created_at)
      сейчас источник пуст — trigger_notify_paper_trade отсутствует в БД
  │
  │ asyncio background task в polymarket_bot контейнере
  │ цикл с sleep(2.0) между итерациями
  ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │ Пункт 1: SELECT * FROM paper_trade_notifications                 │
  │          WHERE notified=FALSE                                    │
  │          ORDER BY created_at ASC LIMIT 10                        │
  ├──────────────────────────────────────────────────────────────────┤
  │ Пункт 2: 0 строк → return → sleep(2.0)                           │
  │          (всегда этот путь в текущем deg-состоянии)              │
  ├──────────────────────────────────────────────────────────────────┤
  │ Пункт 3: для каждой записи формируется Markdown-сообщение        │
  │          🟢/🔴 эмодзи + сокр. wallet + market + size + kelly     │
  ├──────────────────────────────────────────────────────────────────┤
  │ Пункт 4: aiohttp POST в Telegram Bot API                         │
  │          chat_id=946830266, токен из TELEGRAM_ALERT_BOT_TOKEN    │
  │   success → пункт 5                                              │
  │   failure → rollback, notified остаётся FALSE,                   │
  │             запись повторно обработается через 2 секунды         │
  │             (бесконечный retry — RF1)                            │
  ├──────────────────────────────────────────────────────────────────┤
  │ Пункт 5: UPDATE paper_trade_notifications                        │
  │          SET notified=TRUE WHERE id=...                          │
  │          + commit                                                │
  │   при сбое БД после успешной Telegram-отправки                   │
  │   → возможен дубликат сообщения в следующем цикле (RF2)          │
  └──────────────────────────────────────────────────────────────────┘
  ▼
ВЫХОД: либо Telegram-сообщение оператору + notified=TRUE,
       либо silent skip (пустой батч),
       либо бесконечный retry (Telegram down).

  Текущее deg-состояние: цепочка не активируется, upstream trigger удалён.
  Восстановление — отдельная задача (применить add_telegram_notifications.sql
  и решить backfill для существующих paper_trades — см. RF3).
```

---

## 16. Open questions

Нет — все ранее открытые вопросы перенесены в §13 RED FLAGs или сняты как нерелевантные.

---

**Конец документа.**
