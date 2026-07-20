# RECON: фактура для спеки авто-аудита фарминга

Дата разведки: 2026-07-20.

Режим: read-only. Используются только чтение файлов и SQL `SELECT`; секретные значения в отчёт не выводятся.

## R1. Схемы и объёмы четырёх таблиц

### Методика

Источник: `information_schema.columns` (`table_schema = 'public'`) и `SELECT count(*)`. Подключение выполнено к `localhost:5433/polymarket`; транзакция psycopg2 принудительно переведена в `readonly=True`, `autocommit=True`.

Все четыре таблицы **существуют**.

### `farming_daily_snapshot`

Полный список колонок (13):

| # | Колонка | Тип |
|---:|---|---|
| 1 | `snap_date` | `date` |
| 2 | `token` | `text` |
| 3 | `gamma_id` | `bigint` |
| 4 | `condition_id` | `text` |
| 5 | `legs_state` | `text` |
| 6 | `hours_both` | `numeric` |
| 7 | `legs_state_log` | `text` |
| 8 | `inv` | `numeric` |
| 9 | `mid` | `numeric` |
| 10 | `capital_usd` | `numeric` |
| 11 | `fees_usd` | `numeric` |
| 12 | `reward_usd` | `numeric` |
| 13 | `created_at` | `timestamp with time zone` (`timestamptz`) |

Всего 55 строк. Суточный ключ — `snap_date`: максимум `2026-07-18`, в этом срезе **5 строк**. Для контроля: 10 разных дат от `2026-07-09` до `2026-07-18`; у пяти строк последнего среза одинаковый `created_at = 2026-07-19 07:38:58.413519+00`.

### `account_positions_snapshot`

Полный список колонок (17):

| # | Колонка | Тип |
|---:|---|---|
| 1 | `id` | `bigint` |
| 2 | `snap_date` | `date` |
| 3 | `account` | `text` |
| 4 | `condition_id` | `text` |
| 5 | `asset` | `text` |
| 6 | `title` | `text` |
| 7 | `size` | `numeric` |
| 8 | `avg_price` | `numeric` |
| 9 | `initial_value` | `numeric` |
| 10 | `current_value` | `numeric` |
| 11 | `cash_pnl` | `numeric` |
| 12 | `realized_pnl` | `numeric` |
| 13 | `cur_price` | `numeric` |
| 14 | `redeemable` | `boolean` |
| 15 | `end_date` | `date` |
| 16 | `raw_json` | `jsonb` |
| 17 | `ingested_at` | `timestamp with time zone` (`timestamptz`) |

Всего 30 строк. Суточный ключ — `snap_date`: максимум `2026-07-19`, в этом срезе **11 строк**. Для контроля: 3 разных `snap_date` от `2026-07-14` до `2026-07-19`; все 11 строк были ingested 19 июля (двумя временными группами).

### `farming_market_candidates`

Полный список колонок (35):

| # | Колонка | Тип |
|---:|---|---|
| 1 | `gamma_id` | `character varying` (`varchar`) |
| 2 | `condition_id` | `character varying` (`varchar`) |
| 3 | `clob_token_ids` | `text` |
| 4 | `question` | `text` |
| 5 | `slug` | `character varying` (`varchar`) |
| 6 | `category` | `character varying` (`varchar`) |
| 7 | `rewards_min_size` | `numeric` |
| 8 | `rewards_max_spread` | `numeric` |
| 9 | `mid` | `numeric` |
| 10 | `best_bid` | `numeric` |
| 11 | `best_ask` | `numeric` |
| 12 | `liquidity_clob` | `numeric` |
| 13 | `volume_24hr_clob` | `numeric` |
| 14 | `end_date` | `timestamp with time zone` (`timestamptz`) |
| 15 | `days_to_end` | `integer` |
| 16 | `required_capital` | `numeric` |
| 17 | `funnel_stage` | `integer` |
| 18 | `reward_pool_daily_rate` | `numeric` |
| 19 | `book_depth_bid_notional` | `numeric` |
| 20 | `book_depth_ask_notional` | `numeric` |
| 21 | `competitor_weight` | `numeric` |
| 22 | `est_share` | `numeric` |
| 23 | `est_daily_yield_pct` | `numeric` |
| 24 | `scan_run_id` | `uuid` |
| 25 | `scanned_at` | `timestamp with time zone` (`timestamptz`) |
| 26 | `is_deep_scanned` | `boolean` |
| 27 | `our_daily_usd` | `numeric` |
| 28 | `fees_enabled` | `boolean` |
| 29 | `neg_risk` | `boolean` |
| 30 | `tick` | `numeric` |
| 31 | `moves2c` | `integer` |
| 32 | `dead_book` | `boolean` |
| 33 | `bid_depth_usd` | `numeric` |
| 34 | `ask_depth_usd` | `numeric` |
| 35 | `thin_book` | `boolean` |

Всего 768 строк. Типовой срез здесь является scan-батчем (`scan_run_id`/`scanned_at`), а не календарным днём: максимальный `scanned_at = 2026-07-19 21:00:32.054228+00`, при точном равенстве этому timestamp **26 строк**. На всём календарном дне 19 июля — 81 строка, то есть смешение нескольких батчей; для «последнего среза» далее используется именно последний батч из 26 строк.

### `account_activity`

Полный список колонок (20):

| # | Колонка | Тип |
|---:|---|---|
| 1 | `id` | `bigint` |
| 2 | `account` | `text` |
| 3 | `proxy_wallet` | `text` |
| 4 | `event_type` | `text` |
| 5 | `condition_id` | `text` |
| 6 | `asset` | `text` |
| 7 | `side` | `text` |
| 8 | `size` | `numeric` |
| 9 | `usdc_size` | `numeric` |
| 10 | `price` | `numeric` |
| 11 | `outcome_index` | `integer` |
| 12 | `title` | `text` |
| 13 | `slug` | `text` |
| 14 | `event_ts` | `timestamp with time zone` (`timestamptz`) |
| 15 | `tx_hash` | `text` |
| 16 | `raw_json` | `jsonb` |
| 17 | `ingested_at` | `timestamp with time zone` (`timestamptz`) |
| 18 | `source` | `text` |
| 19 | `fill_seq` | `integer` |
| 20 | `trade_role` | `text` |

Всего 356 строк. Для суточного фактического среза используется бизнес-время `event_ts`: последняя доступная UTC-дата — `2026-07-19`, на ней **1 строка** (максимум `event_ts = 2026-07-19 00:00:10+00`). `ingested_at` здесь не является временем события: 19 июля было загружено 13 строк, в том числе исторические события.

## R2. Оценка объёма промпта в токенах

### Методика среза

Каждый набор строк получен `SELECT *` и сериализован буквально через `json.dumps(rows, ensure_ascii=False, default=str)`. «Суммарно» ниже — сумма длин четырёх отдельных JSON-массивов; оценка токенов дана требуемым диапазоном `символы / 4 … символы / 3`.

* `farming_daily_snapshot`: `snap_date = max(snap_date)` (`2026-07-18`).
* `account_positions_snapshot`: `snap_date = max(snap_date)` (`2026-07-19`).
* `farming_market_candidates`: последний `scan_run_id` по `max(scanned_at)`; у подтверждённого батча 26 строк и единый `scanned_at = 2026-07-19 21:00:32.054228+00`.
* `account_activity`: реальные последние 24 часа относительно DB clock. В момент замера DB clock был `2026-07-20 06:23:56.418780+00`, граница — `2026-07-19 06:23:56.418780+00`. Результат — 0 строк, потому что максимальный `event_ts` в таблице равен `2026-07-19 00:00:10+00`, то есть старше границы. JSON пустого массива имеет 2 символа.

### (а) Сырой JSON всех строк

| Срез | Строк | Символов | Грубая оценка токенов (`/4 … /3`) |
|---|---:|---:|---:|
| `farming_daily_snapshot` | 5 | 3 546 | 887 … 1 182 |
| `account_positions_snapshot` | 11 | 16 969 | 4 242 … 5 656 |
| `farming_market_candidates` | 26 | 31 745 | 7 936 … 10 582 |
| `account_activity` (последние 24 ч) | 0 | 2 | 1 … 1 |
| **Итого** | **42** | **52 262** | **13 066 … 17 421** |

### (б) Усечённый дайджест, top-N=20 позиций/кандидатов

Для воспроизводимой прикидки позиции отсортированы по `current_value DESC NULLS LAST, id`, кандидаты — по `est_daily_yield_pct DESC NULLS LAST, gamma_id`. Позиции не урезались (их всего 11); кандидаты сокращены с 26 до 20. Суточный farming-срез и activity оставлены как есть.

| Срез | Строк | Символов | Грубая оценка токенов (`/4 … /3`) |
|---|---:|---:|---:|
| `farming_daily_snapshot` | 5 | 3 546 | 887 … 1 182 |
| `account_positions_snapshot` (top 20, фактически 11) | 11 | 16 969 | 4 242 … 5 656 |
| `farming_market_candidates` (top 20) | 20 | 24 437 | 6 109 … 8 146 |
| `account_activity` (последние 24 ч) | 0 | 2 | 1 … 1 |
| **Итого** | **36** | **44 954** | **11 239 … 14 985** |

Вывод по фактическому последнему набору: простое ограничение top-20 снижает payload только на 7 308 символов (около 14%), поскольку позиции уже короче лимита, а `raw_json` остаётся внутри строк.


## R3. Инвентарь `executor/farming_control_bot.py`

### Получение апдейтов

Это не `python-telegram-bot` и не webhook: файл использует собственный диспетчер поверх `requests` и Telegram Bot API. В бесконечном цикле вызывается long-polling:

```python
updates = tg_request("getUpdates", {"offset": offset, "timeout": 30})
```

Источник: `executor/farming_control_bot.py:453`. После каждого update код сдвигает `offset = update["update_id"] + 1` (`:459-460`). Webhook-кода нет.

### Команды и callback-механика

Диспетчер `handle_command()` (`executor/farming_control_bot.py:361-437`) сравнивает текст на точное равенство. Фактические команды:

* `/status` (`:365`);
* `/stop` (`:368`);
* `/confirm_stop` (`:386`);
* `/start` (`:399`);
* `/confirm_start` (`:416`);
* `/cancel` и синоним `/no` (`:429`).

Неизвестная команда возвращает `None` и молча игнорируется (`:436-437`). Обработчиков `CommandHandler` нет — это самописный `if`/`elif`.

**Callback query сейчас не поддерживаются.** Цикл извлекает только `update.get("message", {})`, затем только `message.text` (`executor/farming_control_bot.py:461-463`). Поиск литералов `callback_query`, `CallbackQueryHandler`, `inline_keyboard`, `reply_markup`, `CommandHandler` в файле дал 0 совпадений. `send_message()` передаёт только `chat_id`, `text`, `parse_mode` (`:132-139`); inline-клавиатура не отправляется.

### Whitelist

Конфигурация и сам whitelist (`executor/farming_control_bot.py:54-58`):

```python
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Whitelist: only process commands from this chat_id
ALLOWED_CHAT_ID = TELEGRAM_CHAT_ID
```

Проверка (`executor/farming_control_bot.py:461-467`):

```python
chat_id = str(msg.get("chat", {}).get("id", ""))
# ...
if chat_id != ALLOWED_CHAT_ID:
    logger.debug("Ignored message from unauthorized chat_id=%s", chat_id)
    continue
```

То есть разрешён ровно один chat id, равный строковому значению `TELEGRAM_CHAT_ID`; отдельного списка пользователей нет.

### Токен и совместное использование с демоном

Токен читается непосредственно через `os.environ.get("TELEGRAM_TOKEN")` (`executor/farming_control_bot.py:54`); `load_dotenv()` в файле нет. URL Bot API строится с этим токеном в `tg_request()` (`:113-114`).

Шапка файла прямо фиксирует общий токен (`executor/farming_control_bot.py:3-8`):

> `Variant A - shared chat, alert bot token reused for control.`
>
> `IMPORTANT: This bot uses long-polling getUpdates with the same token as farming-daemon.`
>
> `Only ONE process can use getUpdates at a time per token.`
>
> `If a second listener is added - it will conflict and steal updates from this bot.`

### Архитектурный вывод

Текущий процесс **технически расширяем**: в него можно добавить разбор `update["callback_query"]`, `answerCallbackQuery` и `reply_markup.inline_keyboard`, поскольку низкоуровневый `tg_request()` уже умеет вызывать произвольный метод Bot API. Но готовой callback-абстракции/фреймворка нет, всё придётся добавить в самописный цикл.

Отдельный процесс callback-кнопок с тем же токеном запускать нельзя: он станет вторым потребителем `getUpdates` и будет конфликтовать, что прямо отражено в шапке. Для отдельного процесса нужен отдельный bot token либо единый процесс-получатель с внутренней маршрутизацией апдейтов.


## R4. Паттерн секретов

Имена извлечены из фактического `.env` скриптом, который разбирает только левую часть до `=` и никогда не выводит правую. По маске `TELEGRAM_*`, `*_KEY`, `*_TOKEN`, `*_SECRET` найдены только следующие имена:

* `BUILDER_API_KEY`
* `BUILDER_API_SECRET`
* `OPENROUTER_API_KEY`
* `POLYMARKET_API_KEY`
* `POLYMARKET_API_SECRET`
* `POLYMARKET_PRIVATE_KEY`
* `TELEGRAM_ALERT_BOT_TOKEN`
* `TELEGRAM_CHAT_ID`

Значения намеренно не читались в отчёт и не приводятся.

**OpenRouter/LLM-ключ уже предусмотрен:** в `.env` фактически есть имя `OPENROUTER_API_KEY`. Оно не только объявлено, но и используется: `scripts/run_weekly_whale_analysis.py:40` читает `os.environ.get("OPENROUTER_API_KEY")`, а `:365-369` проверяет наличие и формирует Authorization header. Отдельного имени с подстрокой `LLM` нет. Таким образом, гипотеза «переменной, скорее всего, нет» по текущему состоянию репозитория не подтвердилась.

Типичный паттерн CLI-скриптов — загрузить корневой `.env` через python-dotenv, затем читать `os.environ.get`/`os.getenv`:

```python
from dotenv import load_dotenv
load_dotenv()
# ...
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_ALERT_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
```

Источник: `scripts/run_weekly_whale_analysis.py:17,27,38-40`. Ещё один пример того же паттерна: `scripts/pipeline_monitor.py:22-24,35-36`.

Executor-процессы, напротив, могут полагаться на уже переданное окружение без `load_dotenv`: `executor/farming_control_bot.py:54-55` вызывает `os.environ.get()` напрямую. Для DB-настроек также используется прямой `os.getenv`, например `scripts/fetch_account_activity.py:26-30` (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`).


## R5. Логи `halt` / `pause` / `one_sided`

**Вывод: реальные episode-логи демона на S1 НЕДОСТУПНЫ, источник только S2.**

- Control-бот читает episode-лог по пути `FARMING_DAEMON_LOG =
  /opt/executor/logs/farming_daemon.log` (`executor/farming_control_bot.py`,
  функция `get_last_market_log`). Это S2-путь деплоя демона.
- На S1 по этому пути лежит только **тестовый артефакт** (7478 байт, mtime
  2026-07-19 14:07): строки вида `Test Market`, `reason=test reason` — остаток
  от прогона юнит-тестов бота на S1; `/opt/executor/app/` пуст, живого демона
  и `farming_state.json` на S1 нет.
- Формат реальной строки episode-лога (подтверждён по тест-фикстуре, совпадает
  с боевым):
  `[YYYY-MM-DD HH:MM:SS] [FARM-011/012] PAUSE on <market>: reason=<...> min_left=<..>m (until=<epoch>)`
  и `[ts] [reconcile] tracked leg(s) missing from book (filled/rejected): [...] -> fill-pause (FARM-012)`.
- **Существо one_sided/both-legs при этом доступно на S1** через
  `farming_daily_snapshot.legs_state` / `legs_state_log` / `hours_both` — то есть
  для аудита Ф1 episode-лог S2 не обязателен; он лишь обогащает pause/reconcile-детали
  (опциональный FARM-047, изменение демона на S2).
