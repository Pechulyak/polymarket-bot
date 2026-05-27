# ШАГ 5. АНАЛИТИКА ДЛЯ GOVERNANCE-РЕШЕНИЯ

## Краткая характеристика (TL;DR)

Шаг 5 — **первый шаг governance-контура** магистрали. Входной материал — агрегаты `whales.total_pnl_usd`, `win_rate_confirmed`, `total_roundtrips`, обновлённые финальным шагом первого потока (`update_whale_pnl_from_roundtrips`, шаг 4). Выходной материал — информированный взгляд оператора на каждого кита: «остаётся ли он в текущем `copy_status`, нужно ли повышение / понижение / исключение».

### Шаг 5 в бизнес-нотации

Шаг состоит из трёх параллельных источников аналитики, работающих в **едином еженедельном governance-окне** оператора:

**Автоматические компоненты (cron на хосте):**
- **Weekly AI whale analysis** — каждое воскресенье в 09:00 UTC скрипт собирает метрики per-кит за последние 4 недели (PnL, WR, skip rate, roundtrip stats), плюс кандидатов из `copy_status='none'`, плюс агрегаты по рыночным категориям, отправляет в OpenRouter, сохраняет ответ модели в `whale_ai_analysis` и рассылает в Telegram рекомендации с готовыми SQL-командами.
- **Daily Whale Alert Monitor** — каждый день в 08:00 UTC скрипт проверяет несколько условий (paper inactive, tracked inactive, skip-rate issues, WR degradation) и шлёт алерт в Telegram. Информационный backstop между еженедельными окнами; критические события не остаются незамеченными до воскресенья.

**Ручной компонент (DBeaver):**
- **Manual SQL-инструменты** — оператор раз в неделю, после получения Weekly AI alert, запускает два личных SQL-скрипта вручную:
  - `whale_audit.sql` — обзорный аудит всех китов (WR, profit factor, POST-RESET метрики, ROI on volume, активность).
  - `whale_status.sql` — глубокий разбор **одного** кита (5 секций по таблицам: whales / whale_trades / whale_trade_roundtrips / paper_trades / paper_simulation_pnl).

Три источника **не дублируют, а дополняют друг друга**: Weekly AI даёт рекомендацию модели + кандидатов, Daily Alert сигнализирует о деградации в межнедельном окне, manual SQL — финальная верификация перед UPDATE. Шаг 5 ничего не пишет в `whales`; запись делается на следующем шаге 6.

---

## 1. Назначение шага

Шаг обеспечивает **информационную базу для governance-решения**. Без шага 5 у оператора нет систематического обзора состояния китов, структурированного под решения о смене `copy_status`.

Бизнес-смысл: «у нас есть свежие агрегаты P&L всех китов → собрали отчёты для оператора → оператор готов принимать решения».

Шаг **обязательно предшествует** шагу 6 (manual UPDATE `whales.copy_status`). По правилам `WHALE_STATUS_TRANSITIONS.md v1.1` §11.2 пункт 5, запуск `whale_status.sql` перед promotion в paper является **mandatory** — без выполненного шага 5 решение шага 6 формально нарушает governance-spec.

---

## 2. Статус

Шаг состоит из трёх под-компонентов с **разными статусами**:

| Под-компонент | Имя | Статус | Дата верификации |
|---|---|---|---|
| Автоматический | Weekly AI whale analysis (`run_weekly_whale_analysis.py`) | **CONFIRMED-ACTIVE** (cron) | 2026-05-25 |
| Автоматический | Daily Whale Alert Monitor (`run_daily_whale_alert.py`) | **CONFIRMED-ACTIVE** (cron) | 2026-05-25 |
| Ручной | `whale_audit.sql` + `whale_status.sql` (DBeaver) | **MANUAL-ACTIVE** (еженедельно) | 2026-05-25 |

Автоматические компоненты — cron-задачи на хосте, регистрация в crontab подтверждена. Ручной компонент — личные инструменты оператора, запуск через DBeaver, никакой docker- или cron-обёртки нет; ритм запуска — раз в неделю в рамках того же governance-окна, что и Weekly AI.

---

## 3. Исходные файлы

### Weekly AI (автоматический)

- `scripts/run_weekly_whale_analysis.py` — основной скрипт. SQL-блоки `collect_metrics()`: чтение `whales`, `whale_trade_roundtrips` (с фильтром `pnl_status='CONFIRMED'`), `whale_trades`, агрегация по `market_category`. Вызов AI через OpenRouter API. Запись в `whale_ai_analysis`. Отправка через `send_telegram()`.
- `migrations/add_whale_ai_analysis.sql` — DDL целевой таблицы `whale_ai_analysis`.

### Daily Alert (автоматический)

- `scripts/run_daily_whale_alert.py` — основной скрипт. Несколько функций `check_*`, формирующих HTML-сообщение. Отправка в Telegram, без записи в БД.

### Manual SQL (ручной)

- `scripts/whale_audit.sql` — обзорный аудит всех китов. POST-RESET метрики (читает `bankroll_reset_at` из `strategy_config`), ROI on volume, активность.
- `scripts/whale_status.sql` — deep dive одного кита. Параметризован по `wallet_address` (оператор редактирует строку 4 перед запуском). Секции организованы по `section_ord`.

### Целевые объекты

- Таблица `whale_ai_analysis` (только Weekly AI) — единственная точка записи в шаге 5.
- Telegram-канал/чат (Weekly AI, Daily Alert) — определяется `TELEGRAM_CHAT_ID` из environment.

---

## 4. Контейнер

| Под-компонент | Контейнер / runner |
|---|---|
| Weekly AI | Хост; cron через crontab; рабочий каталог `/root/polymarket-bot`. БД доступна напрямую через `DATABASE_URL`. |
| Daily Alert | Хост; cron через crontab; рабочий каталог `/root/polymarket-bot`. |
| Manual SQL | Машина оператора; DBeaver-клиент с подключением к `polymarket_postgres`. **Не входит в production-инфраструктуру**, не покрыт healthcheck, не виден в `docker ps`. |

Контейнер `bot` шаг 5 не выполняет. Контейнер `whale-detector` — тоже нет.

---

## 5. Триггер запуска и расписание

### Weekly AI (автоматический)

- **Cron expression:** `0 9 * * 0` (каждое воскресенье в 09:00 UTC).
- Регистрация: в crontab хоста.
- Команда: `cd /root/polymarket-bot && python3 scripts/run_weekly_whale_analysis.py >> logs/weekly_whale_analysis.log 2>&1`

### Daily Alert (автоматический)

- **Cron expression:** `0 8 * * *` (каждый день в 08:00 UTC).
- Регистрация: в crontab хоста.

### Manual SQL (ручной)

- **Триггер:** оператор открывает governance-окно в воскресенье после получения Weekly AI alert в Telegram, переключается в DBeaver, выполняет `whale_audit.sql`, при необходимости детального разбора отдельных китов — `whale_status.sql` с подставленным `wallet_address`.
- **Расписание:** еженедельное, привязано к ритму Weekly AI; ad-hoc запуски (при критическом Daily Alert) — на усмотрение оператора.
- **Не зарегистрировано в системе:** нет crontab, нет supervisor, нет docker. Воспроизводимость гарантируется ритуалом оператора, не инфраструктурой.

---

## 6. Алгоритм шага

### Weekly AI whale analysis

1. **Сбор метрик.** Функция `collect_metrics()` выполняет три SQL-блока подряд:
   - Блок 1: per-whale метрики за 4 недели — weekly PnL (из `whale_trade_roundtrips` с `pnl_status='CONFIRMED'`), skip ratio (из `whale_trades` за 7 дней), агрегаты roundtrip-ов.
   - Блок 2: кандидаты на promotion — киты с `copy_status='none'` и ≥30 closed CONFIRMED-roundtrips.
   - Блок 3: статистика по `market_category` — confirmed_count, avg/total net_pnl, win_rate.
2. **Подготовка input для AI.** Все метрики сериализуются в JSON, читаются параметры `ai_model` и `ai_provider_url` из `strategy_config`, API-ключ — `OPENROUTER_API_KEY` из environment.
3. **Вызов AI.** HTTP POST на `ai_provider_url` (OpenRouter) с моделью из `ai_model`, payload — собранные метрики плюс prompt-инструкции. Ответ парсится в `recommendations_json` и `red_flags_json`; флаг `requires_human_review` устанавливается по логике скрипта.
4. **Запись результата.** INSERT в `whale_ai_analysis` со всеми полями (`raw_input_json`, `raw_output_json`, `recommendations_json`, `red_flags_json`, `requires_human_review`, `model_used`).
5. **Отправка в Telegram.** Форматирование summary, HTTP POST на `https://api.telegram.org/bot{TOKEN}/sendMessage` с `chat_id` из env. После успешной отправки — UPDATE `telegram_sent_at` в свежесозданной строке `whale_ai_analysis`.
6. **Ошибки парсинга** ответа AI — пишутся в `error_log` без прерывания записи.

### Daily Whale Alert Monitor

1. Скрипт выполняет несколько независимых SQL-проверок:
   - `check_paper_inactive` — paper-киты, у которых `last_active_at` старше порога.
   - `check_tracked_inactive` — то же для tracked.
   - `check_skip_rate` — JOIN `whales × whale_trades × paper_trades` за 7-дневное окно, доля сделок кита без соответствующей paper-сделки.
   - `check_wr_degradation` — `whale_trade_roundtrips` за последние 14 дней, киты с просевшим WR.
2. Результаты каждой проверки агрегируются в одно HTML-сообщение. Блоки без сработавших условий в финальное сообщение не попадают.
3. Сообщение отправляется в Telegram.

### Manual SQL

1. Оператор открывает DBeaver, подключается к `polymarket_postgres` через service-аккаунт.
2. Выполняет `whale_audit.sql` целиком — получает таблицу всех китов (одна строка на кита) с метриками: WR / Profit Factor, POST-RESET (rt_post, wins_post, losses_post, net_pnl_post), PnL distribution (median, max_win, max_loss), ROI on volume (net_pnl_post / volume_post), активность (days_inactive, last_closed_at).
3. По результатам аудита оператор выбирает кандидатов на promotion / demotion / exclusion.
4. Для каждого кандидата — редактирует строку 4 в `whale_status.sql`, подставляя `wallet_address`, и выполняет скрипт. Получает развёрнутый отчёт по секциям (см. §8).
5. На основе сводки трёх под-компонентов оператор формирует план UPDATE-ов для шага 6.

`whale_audit.sql` и `whale_status.sql` — **read-only**, ничего не модифицируют. Запись в БД на шаге 5 производится только Weekly AI (в `whale_ai_analysis`); Daily Alert и Manual SQL записей в БД не делают.

---

## 7. Формат входных данных

### Weekly AI / Daily Alert — таблицы и view

- `whales` — поля: `wallet_address`, `copy_status`, `tier`, `last_active_at`, `last_targeted_fetch_at`, `total_pnl_usd`, `win_rate_confirmed`, `total_roundtrips`, `estimated_capital`.
- `whale_trades` — поля: `wallet_address`, `market_id`, `side`, `size_usd`, `traded_at`, `market_category`.
- `whale_trade_roundtrips` — поля: `wallet_address`, `market_id`, `outcome`, `status`, `close_type`, `net_pnl_usd`, `pnl_status`, `closed_at`.
- `paper_trades` — поля: `whale_address`, `market_id`, `side`, `kelly_size`, `created_at`, `tx_hash`.
- `strategy_config` — ключи: `ai_model`, `ai_provider_url`, `bankroll_reset_at`.

### Weekly AI — параметры окружения

- `OPENROUTER_API_KEY` — API-ключ AI-провайдера.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — параметры отправки.
- `DATABASE_URL` — подключение к БД.

### Manual SQL — параметр оператора

- `wallet_address` — единственный параметр `whale_status.sql`. Подставляется оператором в строку 4. Корректность адреса (lower-case, валидный hex) — на оператора.

---

## 8. Формат выходных данных

### Weekly AI — три выходных артефакта

1. **Запись в `whale_ai_analysis`** — структурированный результат для аудита и downstream-чтения.
2. **Telegram-сообщение** — рекомендации модели в человекочитаемом формате с готовыми SQL-командами (оператор может скопировать в DBeaver и выполнить как часть шага 6).
3. **Файл лога** `logs/weekly_whale_analysis.log` — stdout/stderr скрипта.

### Daily Alert — один артефакт

- **Telegram HTML-сообщение** с блоками сработавших проверок и счётчиками. В БД не пишется.

### Manual SQL — два артефакта (psql-вывод)

- `whale_audit.sql` — вертикальная таблица: по строке на кита, колонки с метриками. Открывается в DBeaver, оператор скроллит / экспортирует в CSV при необходимости.
- `whale_status.sql` — длинная таблица с колонками `section_ord`, `ord`, `source_table`, `metric`, `value`. Секции:

  | Секция | Источник | Что показывает |
  |---|---|---|
  | §100 | `whales` | базовые поля (copy_status, tier, estimated_capital, native counters) |
  | §200 | `whale_trades` | размеры сделок, распределение side/source/category, временной диапазон, контекст pre/post-reset |
  | §300 | `whale_trade_roundtrips` | total/closed/open count, WR версии A (close_type) и B (net_pnl), PnL stats, post-reset метрики |
  | §400 | `paper_trades` | kelly_size / size_usd distribution, sanity checks, pre/post-reset counts |
  | §500 | `paper_simulation_pnl` | result distribution, PnL stats, pnl_transmission_ratio |

  Никаких сохранений на диск — оператор работает с выводом в DBeaver-сессии.

---

## 9. Записи в БД

Шаг 5 записывает **в одну таблицу** и только из одного под-компонента (Weekly AI). Daily Alert и Manual SQL — read-only.

### `whale_ai_analysis` (INSERT из Weekly AI, один INSERT на запуск скрипта)

| Колонка | Тип | Бизнес-смысл |
|---|---|---|
| `id` | SERIAL PK | технический идентификатор запуска |
| `created_at` | TIMESTAMPTZ | время старта скрипта |
| `model_used` | VARCHAR(100) | какая AI-модель отвечала |
| `raw_input_json` | JSONB | метрики, отправленные в AI |
| `raw_output_json` | JSONB | сырой ответ модели |
| `recommendations_json` | JSONB | распарсенные рекомендации по китам |
| `red_flags_json` | JSONB | флаги риска, выделенные моделью |
| `requires_human_review` | BOOLEAN | требуется ли явная проверка оператором |
| `telegram_sent_at` | TIMESTAMPTZ | время успешной отправки в Telegram (NULL если упало) |
| `error_log` | TEXT | ошибки парсинга ответа AI |

**Что НЕ обновляется на шаге 5** (важно для отличия от шага 6):
- `whales.copy_status` — только на шаге 6
- `whales.reviewed_at`, `whale_comment`, `exclusion_reason` — только на шаге 6
- `paper_trades`, `paper_trade_notifications` — это шаг 7 (paper trading lifecycle)
- materialized views — refresh-ом на своём cron, не из шага 5

---

## 10. Условия успеха / частичного успеха / неуспеха

### Weekly AI

| Исход | Условие | Поведение |
|---|---|---|
| Полный успех | SQL-сбор + AI-вызов + INSERT + Telegram прошли | строка в `whale_ai_analysis` с заполненным `telegram_sent_at`, оператор получил сообщение |
| Частичный успех (AI вернул, Telegram упал) | `INSERT` прошёл, `send_telegram()` бросил исключение | строка в `whale_ai_analysis` есть, `telegram_sent_at = NULL`; оператор узнаёт только при следующем входе в DBeaver |
| Парсинг AI не удался | AI вернул, но `recommendations_json` не извлечься | `raw_output_json` сохранён, `error_log` заполнен, `requires_human_review = TRUE`, Telegram-сообщение деградирует до raw-выдержки |
| AI-вызов упал | таймаут / 5xx / неверный ключ | строка в `whale_ai_analysis` **не создаётся** (скрипт падает раньше INSERT), оператор узнаёт только через монитор логов |
| Пустой dataset | в `whale_trade_roundtrips` нет confirmed-roundtrip-ов | SQL вернёт пусто, AI получит пустой блок 1; ответ модели — пустой / низкого качества |

### Daily Alert

| Исход | Условие | Поведение |
|---|---|---|
| Полный успех | проверки выполнены, Telegram отправлен | алерт в чате; оператор информирован |
| Частичный успех | одна из проверок упала, остальные ОК | в сообщении пропущенный блок, остальные есть; в логе stacktrace |
| Полная неуспех | SQL/Telegram оба упали | сообщение не пришло; диагностика только через `logs/` |

### Manual SQL

| Исход | Условие | Поведение |
|---|---|---|
| Полный успех | DBeaver вернул таблицы без ошибок | оператор видит данные, идёт в шаг 6 |
| Ошибка SQL | синтаксическая правка оператора, версия БД несовместима | DBeaver покажет ошибку; шаг блокируется до правки скрипта оператором |
| Оператор пропустил неделю | governance-окно не открыто | алгоритм просто не выполняется; никаких автоматических напоминаний (см. RED FLAG #5) |

---

## 11. Зависимости

### Upstream

- **Шаги 3A / 3B / 3C первого потока** — заполняют `whale_trade_roundtrips` (3A создаёт OPEN, 3B закрывает через settlement, 3C закрывает через SELL — реактивирован TRD-443, host cron `15 * * * *`). Это основной источник для Weekly AI и Manual SQL.
- **Шаг 4 первого потока** (`update_whale_pnl_from_roundtrips`) — обеспечивает свежесть агрегатов в `whales`. Если шаг 4 не отрабатывал N дней (cron-сбой), все три под-компонента шага 5 будут читать устаревшие данные. Шаг 5 этого не детектирует.
- **`strategy_config.bankroll_reset_at`** — определяет границу pre/post-reset для Weekly AI (Блок 1) и Manual SQL (post-reset метрики в §200/§300/§400). Корректность значения reset-таймштампа — на STRATEGY.

### Downstream

- **Шаг 6** — основной потребитель: оператор использует выводы Weekly AI / Daily Alert / Manual SQL как input для принятия решения об UPDATE `copy_status`.
- **`whale_ai_analysis`** как таблица не имеет **никаких других потребителей** в системе. Ни код, ни cron не читают эту таблицу для downstream-аналитики. Telegram-сообщение — единственный канал передачи рекомендации оператору; запись в БД служит audit-trail и потенциальным input'ом для будущей аналитики (см. RED FLAG #3).

### External

| Сервис | Используется в | Что отправляется | Что возвращается |
|---|---|---|---|
| **OpenRouter API** (`ai_provider_url` из `strategy_config`) | Weekly AI | JSON с метриками китов + prompt | JSON с рекомендациями (recommendations, red_flags) |
| **Telegram Bot API** (`api.telegram.org`) | Weekly AI, Daily Alert | HTML/Markdown текст | ack |
| **DBeaver** (клиент оператора) | Manual SQL | SQL-скрипт | таблица результатов в UI |

API-ключи и токены — из environment, в коде / документации не отображаются.

### Параллельные процессы

- **`pipeline_monitor`** (cron `*/30`) — отдельный мониторинг состояния pipeline через Telegram; не входит в governance-контур, но конкурирует за внимание оператора в том же Telegram-чате. Не блокирует шаг 5.
- **Materialized views refresh** (`scripts/refresh_views.sh`, cron `15 */2 * * *`) — параллельно обновляет `whale_pnl_summary`, `paper_portfolio_state`, `paper_simulation_pnl`. Manual SQL §500 читает `paper_simulation_pnl` — при неудачном тайминге запуска (refresh идёт прямо сейчас) view возвращает stale-данные до завершения refresh.

---

## 12. Наблюдаемость

### Логи

- Weekly AI: `logs/weekly_whale_analysis.log` — stdout/stderr скрипта, append-режим.
- Daily Alert: лог в Telegram сам по себе (сообщение + статус), плюс stdout cron-задачи.
- Manual SQL: только DBeaver-сессия оператора; никаких persistent-логов.

### Метрики

- Не экспортируются. Состояние Weekly AI проверяется SELECT-запросом к `whale_ai_analysis` (последние записи: `created_at`, `model_used`, `telegram_sent_at`, `requires_human_review`, наличие `error_log`).
- Состояние Daily Alert проверяется только по факту получения Telegram-сообщения оператором (нет фиксации в БД).
- Manual SQL — наблюдаемость **полностью на ритуале оператора**; нет события «оператор запустил whale_audit на этой неделе».

### Что наблюдатель НЕ видит

- Не видит, кто из китов попал в Weekly AI input на неделе X, если запись в `whale_ai_analysis` не создалась (AI-вызов упал до INSERT).
- Не видит, прочитал ли оператор Telegram-сообщение и принял ли решение.
- Не видит расхождения между рекомендацией AI и фактическим UPDATE на шаге 6 (нет связи `whale_ai_analysis.id` → последующий UPDATE).
- Не видит, выполнил ли оператор `whale_status.sql` перед promotion (mandatory по `WHALE_STATUS_TRANSITIONS.md` §11.2 пункт 5, но не enforced ни кодом, ни БД).

---

## 13. Особые случаи и риски (RED FLAGs)

**RF1 [governance — материализован] — Mandatory `whale_status.sql` не enforced.**
По `WHALE_STATUS_TRANSITIONS.md v1.1` §11.2 пункт 5, перед promotion в paper запуск `whale_status.sql` обязателен, и его результаты — authoritative при расхождении с audit-отчётами (>5pp WR, >10% PnL). Однако никакой проверки запуска нет: оператор может выполнить шаг 6 без Manual SQL, и БД примет UPDATE. Защита — только ритуал оператора и его дисциплина.

**RF2 [resilience — материализован] — Weekly AI без идемпотентности и retry.**
Если cron упал в воскресенье 09:00 (ошибка БД, OpenRouter недоступен), повторный запуск выполняется только через неделю. Ручной перезапуск технически возможен (`python3 scripts/run_weekly_whale_analysis.py`), но не предписан процессом. Если запуск прошёл частично (AI вернул, Telegram упал), повторный запуск создаст **вторую запись** в `whale_ai_analysis` за то же воскресенье — никакого UNIQUE constraint по `(DATE(created_at), …)` нет.

**RF3 [latent — accumulating] — `whale_ai_analysis` накапливается без потребителей и без retention policy.**
Каждая запись — `raw_input_json` + `raw_output_json` могут быть десятки килобайт JSONB. Никаких downstream-консьюмеров нет, никакой ротации тоже. Через год работы таблица содержит ~52 строки и весит относительно немного, но JSONB-индексы не созданы — любая аналитика по recommendations потребует full scan. Минимально кандидат на: (a) retention 6m / 12m, (b) GIN-индекс по `recommendations_json` при появлении первого аналитического запроса.

**RF4 [governance — материализован] — Markdown-инъекция AI в Telegram.**
Weekly AI отправляет AI-ответ в Telegram. Если модель вернёт текст с активными ссылками / markdown-эскейпами, оператор может скопировать в DBeaver SQL-команду, которая выглядит валидной, но содержит скрытые манипуляции. Зона риска: рекомендации в виде готового `UPDATE whales SET copy_status = 'paper' WHERE wallet_address = '0x…'`. Защита — внимательность оператора + правило: «копируем рекомендацию модели, перепроверяем wallet и условия в DBeaver, никогда не делаем blind paste».

**RF5 [process — материализован] — 7-дневное реактивное окно.**
Оператор открывает governance-окно раз в неделю. Если кит между воскресеньями деградирует (например, поведение `auto_market_maker` начало проявляться во вторник), реакция возможна только через 5 дней. Daily Whale Alert Monitor частично компенсирует (`check_skip_rate`, `check_wr_degradation`), но: (a) пороги Daily Alert могут не сработать для конкретного паттерна, (b) ad-hoc реакция требует от оператора решения «запустить Manual SQL вне ритма», что не предписано процессом.

**RF6 [hygiene — latent] — Manual SQL без audit-trail.**
Запуски `whale_audit.sql` и `whale_status.sql` не оставляют следов в БД или логах. Нет таблицы `governance_audit_log`, нет автоматической записи «оператор смотрел кита X в дату Y». При расследовании прошлого решения шага 6 (например, «почему 3 недели назад кит был переведён в excluded») восстановить контекст невозможно — только по своей памяти / переписке.

**RF7 [hygiene — low priority] — `whale_audit.sql` и `whale_status.sql` живут только в репозитории.**
Любое изменение скриптов оператором локально (в DBeaver) не отражается в git, если оператор не сделал коммит. Реальная версия SQL может расходиться с версией в репозитории. Защита — дисциплина: запускать только версию из git checkout, любые изменения коммитить отдельной задачей.

**RF8 [data — материализован] — `pnl_status='CONFIRMED'` фильтр в Weekly AI vs другой фильтр в audit.**
`run_weekly_whale_analysis.py` Блок 1 фильтрует roundtrip-ы по `pnl_status='CONFIRMED'`. `whale_audit.sql` фильтрует по другому критерию (POST-RESET через `closed_at >= bankroll_reset_at`). Метрики могут расходиться, и это **корректное расхождение**, но при чтении двух источников подряд оператор должен помнить, что они смотрят на разные подмножества. Защита — fix в документации (этот пункт) и понимание оператора.

**RF9 [observability — материализован] — `check_new_candidates` Daily Alert не приходит в Telegram.**
По наблюдению оператора, блок новых кандидатов на promotion из Daily Alert ни разу не присылался. Причина не верифицирована (требует чтения `run_daily_whale_alert.py`): либо чек существует, но порог настолько строгий, что никогда не срабатывает; либо чек удалён из текущей версии; либо HTML-форматирование пропускает пустые блоки и оператор просто не видит «New candidates: 0». Защита — кандидаты на promotion вычисляются Weekly AI Блоком 2 (`copy_status='none'` с ≥30 confirmed roundtrips), потеря дублирующего канала в Daily Alert не критична.

---

## 14. Результат шага

После полного прохождения еженедельного governance-окна (Weekly AI + Daily Alert + Manual SQL):

- В `whale_ai_analysis` есть новая строка за текущее воскресенье с заполненными `recommendations_json` и `telegram_sent_at`.
- Оператор получил Weekly AI alert и ≥1 Daily Alert за неделю в Telegram.
- Оператор имеет открытый в DBeaver `whale_audit.sql` вывод + при необходимости 1–N выводов `whale_status.sql` по конкретным китам.
- Сформирован **план UPDATE-ов** для шага 6: список китов с целевыми переходами `copy_status` и обоснованиями.

**Состояние объекта магистрали** (кит как governance-сущность): данные о ките собраны, проанализированы, рекомендация сформулирована. Сам `whales.copy_status` ещё **не изменён** — это происходит только на шаге 6.

### Связь со следующим шагом магистрали

**Следующий шаг — 6: manual gate, UPDATE `whales.copy_status`.**

Связь между шагом 5 и шагом 6 — **синхронная в рамках одного governance-окна**: оператор не закрывает DBeaver-сессию после Manual SQL, а в той же сессии переходит к UPDATE-командам шага 6. Все три источника шага 5 (Weekly AI Telegram, whale_audit, whale_status) служат **обоснованием** для каждого UPDATE на шаге 6.

Технически: ничто в БД не связывает строку `whale_ai_analysis.id` с последующими UPDATE-ами `whales.copy_status`. Связь только в `whales.whale_comment` (текстовое поле, заполняется оператором на шаге 6 по правилам `WHALE_STATUS_TRANSITIONS.md` §11). См. RF6 — формального audit-trail между рекомендацией AI и фактическим решением нет.

### Side-route: paper-ветка параллельно

Шаг 5 не порождает paper-сделок. Параллельно (между воскресеньями) контейнер `whale-detector` продолжает писать `whale_trades`, DB-trigger `trigger_copy_whale_trade` продолжает создавать `paper_trades` для текущего набора paper-китов (см. шаг 7). Шаг 5 эти процессы не модифицирует.

---

## 15. Краткая бизнес-формула шага

```
ВХОД: воскресенье 08:00 UTC
  │
  ├── Daily Whale Alert Monitor (cron 0 8 * * *)
  │     │
  │     ├── SELECT checks ← whales, whale_trades, paper_trades, whale_trade_roundtrips
  │     └── HTTP POST → Telegram (HTML, блоки сработавших проверок)
  │
  ▼
ВХОД: воскресенье 09:00 UTC
  │
  ├── Weekly AI whale analysis (cron 0 9 * * 0)
  │     │
  │     ├── SELECT 3 blocks ← whales, whale_trade_roundtrips (CONFIRMED),
  │     │                    whale_trades (7d), market_category aggregates
  │     ├── HTTP POST → OpenRouter (model from strategy_config.ai_model)
  │     ├── parse recommendations_json / red_flags_json
  │     ├── INSERT INTO whale_ai_analysis (...) → одна строка
  │     ├── HTTP POST → Telegram (рекомендации + SQL-команды)
  │     └── UPDATE whale_ai_analysis SET telegram_sent_at = NOW()
  │
  ▼
ВХОД: оператор открывает DBeaver
  │
  └── Manual SQL (ad-hoc, в рамках еженедельного окна)
        │
        ├── cat scripts/whale_audit.sql | DBeaver → таблица per-whale
        │     (WR, profit factor, POST-RESET, ROI on volume, активность)
        │
        └── для каждого кандидата:
              edit line 4 в whale_status.sql: '<wallet_address>'
              run в DBeaver → секции §100 / §200 / §300 / §400 / §500

ВЫХОД: план UPDATE-ов для шага 6 (в голове / заметках оператора)
   ↓
[шаг 6 — manual UPDATE whales.copy_status]
```

---

## 16. Ссылки на governance-spec

Кратко из `WHALE_STATUS_TRANSITIONS.md v1.1` (SSoT правил оператора). Полные тексты — в первоисточнике.

- **§11.1 Перед promotion в tracked** (из `none` или `excluded`): tier refresh через `_update_whale_activity`, проверка `tier ∈ {HOT, WARM}`, лог причины в `whale_comment`. Эти проверки выполняются оператором с опорой на Manual SQL §100 (текущий tier) и §200 (активность).
- **§11.2 Перед promotion в paper** (из `tracked` или `excluded`): all §11.1 + **mandatory `whale_status.sql`** (см. RF1), post-reset adequacy check (`roundtrips_closed_post_reset ≥ 10`, `post_reset_wr ≥ 60%`) → читается из §300 post-reset блока Manual SQL, расчёт `estimated_capital` по методу `max_daily_volume_30d`.
- **§11.3 Перед excluded**: заполнение `exclusion_reason` (`negative_pnl` / `auto_market_maker` / `edge_degraded` / `manual`), проверка открытых paper-позиций (они не закрываются автоматически, доигрываются до settlement — см. шаг 7).
- **§3 Допустимые переходы**: `none→tracked`, `tracked→paper`, `paper→tracked`, `any→excluded`, `excluded→tracked|paper`. Прямой `none→paper` discouraged; downgrade в `none` не поддерживается.

Полная семантика, SQL-шаблоны UPDATE и формулы `estimated_capital` — в `WHALE_STATUS_TRANSITIONS.md`. Документ шага 5 описывает только **сбор данных** для применения этих правил; сами правила исполняются на шаге 6.
