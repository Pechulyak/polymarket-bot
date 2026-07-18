# PIPELINE_MAP_LEADERBOARD_SCORING — Предварительный скоринг кандидатов из Leaderboard

**Статус документа:** ACTIVE  
**Дата верификации:** 2026-06-08  
**Эталон формата:** `PIPELINE_MAP_3A_roundtrip_open.md`  
**Связанные задачи:** PIPE-044, PIPE-045, PIPE-046, PIPE-049, PIPE-050

---

## TL;DR

Изолированный side-pipeline для предварительного скоринга трейдеров из Polymarket Leaderboard до их попадания в production-таблицы. Два скрипта, запускаемых вручную. Первый (`fetch_leaderboard_candidates.py`) загружает топ-20 (`timePeriod=MONTH`), проверяет LP (наличие `REWARD` в `/activity`) и HFT-всплески (peak > 20 сделок/15 мин), сохраняет сделки в staging. Второй (`score_leaderboard_candidates.py`) берёт всех кандидатов с `is_copyable IS NULL`, строит roundtrips, выполняет settlement через CLOB API, записывает агрегаты. Оператор читает результаты и принимает решение вручную; одобренные промоутятся в `whales.copy_status = 'tracked'` через `WHALE_STATUS_TRANSITIONS.md`. Production-таблицы `whales` и `whale_trades` не затрагиваются.

---

## 1. Назначение

Pipeline решает «проблему курицы и яйца»: PnL-анализ невозможен до промоута кандидата в `tracked`, а решение о промоуте принималось без достаточных данных. Pipeline позволяет накопить roundtrip-статистику кандидата до его появления в production, не загрязняя production-таблицы.

**Что pipeline НЕ делает:** не пишет в `whales` и `whale_trades`, не запускается по расписанию, не принимает решения о промоуте автоматически.

---

## 2. Статус

**ACTIVE.** Скрипты задеплоены, таблицы созданы, первый прогон выполнен 2026-06-08.

| Компонент | Статус | Источник |
|-----------|--------|----------|
| Таблицы DDL | CREATED | `migrations/pipe_044_leaderboard_tables.sql` |
| `fetch_leaderboard_candidates.py` | ACTIVE | `scripts/fetch_leaderboard_candidates.py`, 454 строки |
| `score_leaderboard_candidates.py` | ACTIVE | `scripts/score_leaderboard_candidates.py`, 353 строки |

---

## 3. Исходные файлы

| Файл | Роль |
|------|------|
| `scripts/fetch_leaderboard_candidates.py` | Шаг 1: загрузка leaderboard, LP/HFT-фильтрация, запись кандидатов и сделок |
| `scripts/score_leaderboard_candidates.py` | Шаг 2: построение roundtrips, settlement, расчёт скоринг-метрик |
| `migrations/pipe_044_leaderboard_tables.sql` | DDL трёх таблиц pipeline |

---

## 4. Контейнер

Выделенного docker-контейнера нет. Оба скрипта запускаются на хосте. Режим зафиксирован в docstring `score_leaderboard_candidates.py`: `Запускается вручную, без cron и Docker.`

```bash
python3 scripts/fetch_leaderboard_candidates.py
python3 scripts/score_leaderboard_candidates.py
```

---

## 5. Триггер запуска и расписание

| Параметр | Значение | Источник |
|----------|----------|----------|
| Тип триггера | Ручной запуск оператором | docstring `score_leaderboard_candidates.py` |
| Расписание cron (хост) | Отсутствует | `crontab -l \| grep leaderboard` → пусто |
| Расписание cron.d | Отсутствует | `cat /etc/cron.d/* \| grep leaderboard` → пусто |
| Порядок | Сначала fetch, затем score | Зависимость по данным: fetch пишет trades, score их читает |

---

## 6. Алгоритм

### 6.1 `fetch_leaderboard_candidates.py`

**Последовательность `main()`:**

1. **Fetch leaderboard** — `data-api.polymarket.com/v1/leaderboard`, итерация по 9 категориям (POLITICS, ESPORTS, CRYPTO, CULTURE, MENTIONS, WEATHER, ECONOMICS, TECH, FINANCE), TOP_N_PER_CATEGORY=5. OVERALL и SPORTS исключены. Параметры `{"timePeriod": "MONTH", "limit": 50}` (`:375`).
2. **Upsert в `leaderboard_candidates`** — `ON CONFLICT (wallet_address) DO UPDATE` (`:71–90`). Адрес из поля `proxyWallet` (`:379`).
3. **`process_candidate()` для каждого из 20:**
   - **LP-фильтр**: `/activity?user=<wallet>&limit=20` (без фильтра type). Если `type == "REWARD"` → UPDATE `is_lp=TRUE, filter_reason='lp_market_maker'`. Сделки загружаются независимо от результата (`:252–258`).
   - **Fetch сделок**: `/activity?type=TRADE&user=<wallet>&limit=500&offset=N`, пагинация, cutoff 90 дней (`:168`). Дедупликация `ON CONFLICT (tx_hash) DO NOTHING`.
   - **HFT-фильтр**: SQL peak за 15-минутные окна — `date_trunc('hour') + (EXTRACT(MINUTE)/15) * interval '15 minutes'` (`:200–218`). PIPE-051 (2026-07-18): добавлена `burst_trade_pct` — доля 90-дневных сделок кошелька, попавших в окна с `cnt > 20`, от общего числа сделок.
   - **UPDATE**: `is_hft_burst = (peak > 20 AND burst_trade_pct > 50.0)`, `is_copyable = NULL` для всех кандидатов (`:290–302`). До PIPE-051 правило было `is_hft_burst = (peak > 20)` — единичный всплеск за 90 дней ложно флагал обычных трейдеров наравне с ботами (см. RF3 ниже).

**Ключевое:** `is_copyable` остаётся `NULL` для всех — включая LP и HFT. Оба флага информационные.

### 6.2 `score_leaderboard_candidates.py`

**Отбор кандидатов:**
```sql
SELECT wallet_address, username FROM leaderboard_candidates
WHERE is_copyable IS NULL ORDER BY leaderboard_rank
```
Поскольку после fetch все кандидаты имеют `is_copyable IS NULL` — обрабатываются все 20.

**`process_candidate()` для каждого:**

1. **Группировка сделок** — GROUP BY `(wallet_address, market_id, outcome)` по `leaderboard_candidate_trades`. Агрегаты: `open_size_usd` (SUM BUY), `open_price` (средневзвешенная BUY), `close_size_usd` (SUM SELL), `close_price` (средневзвешенная SELL), `buy_count`, `sell_count` (`:64–88`).

2. **Классификация по группе:**

| Условие | `close_type` | `status` | P&L |
|---------|-------------|---------|-----|
| `buy_count > 0 AND sell_count > 0` | `SELL` | `CLOSED` | `(close_price − open_price) × close_size_usd` |
| `buy_count > 0 AND sell_count == 0` | `OPEN` → settlement | `OPEN` → `CLOSED` | см. ниже |
| `buy_count == 0 AND sell_count > 0` | `OPEN` | `OPEN` | `NULL` |

3. **Settlement** (только BUY без SELL) — запрос `https://clob.polymarket.com/markets/<market_id>` (`:37`). Поиск токена с `outcome == group["outcome"]` (exact match). `closed=True AND winner=True` → `SETTLEMENT_WIN`, `close_price=1.0`. `closed=True AND winner=False` → `SETTLEMENT_LOSS`, `close_price=0.0`. Fallback при `matched=False AND closed=True`: первый токен с `winner=True`. При ошибке API или рынок не закрыт: `close_type='OPEN'`.

4. **INSERT/UPDATE в `leaderboard_candidate_roundtrips`** — `ON CONFLICT (wallet_address, market_id, outcome) DO UPDATE` (`:189–230`).

5. **Агрегация → UPDATE `leaderboard_candidates`**: `roundtrips_total`, `roundtrips_closed`, `roundtrips_open`, `wins`, `losses`, `win_rate`, `calc_pnl_usd`, `pnl_calc_method='roundtrip+settlement'`. `is_copyable` остаётся `NULL` (`:232–265`).

### 6.3 Governance (вне скриптов)

STRATEGY читает `leaderboard_candidates`, устанавливает `approved_for_tracking = TRUE` вручную, промоутит через `WHALE_STATUS_TRANSITIONS.md` (переход `none → tracked`).

---

## 7. Входные данные

| API | URL | Параметры | Скрипт |
|-----|-----|-----------|--------|
| Leaderboard | `data-api.polymarket.com/v1/leaderboard` | `timePeriod=MONTH, limit=50` | fetch, `:342` |
| Activity (LP) | `data-api.polymarket.com/activity` | `user=<wallet>, limit=20` | fetch, `:155` |
| Activity (trades) | `data-api.polymarket.com/activity` | `type=TRADE, user=<wallet>, limit=500, offset=N` | fetch, `:168` |
| CLOB (settlement) | `https://clob.polymarket.com/markets/<market_id>` | — | score, `:37` |

LP-фильтр: сигнал — наличие `type == "REWARD"` в ответе `/activity`. Enum типов: `TRADE`, `SPLIT`, `MERGE`, `REDEEM`, `REWARD`, `CONVERSION`.

Размер сделки: `usdcSize` если присутствует, иначе `size × price` (fetch, `:103–109`). Единицы: `size_usd` — USDC, `price` — вероятность 0–1.

---

## 8. Выходные данные

`leaderboard_candidates` — после score заполнены: `roundtrips_total`, `roundtrips_closed`, `roundtrips_open`, `wins`, `losses`, `win_rate`, `calc_pnl_usd`, `pnl_calc_method`. Поле `is_copyable` остаётся `NULL`.

`leaderboard_candidate_roundtrips` — roundtrip-записи по кандидатам.

`leaderboard_candidate_trades` — staging; заполняется при fetch, очищается вручную после governance-решений.

---

## 9. Записи в БД

### DDL — `leaderboard_candidates`

```sql
CREATE TABLE leaderboard_candidates (
    id                      SERIAL PRIMARY KEY,
    wallet_address          VARCHAR(66)   NOT NULL UNIQUE,
    username                VARCHAR(128),
    leaderboard_period      VARCHAR(16),
    leaderboard_rank        INTEGER,
    leaderboard_pnl_usd     NUMERIC(20,2),
    fetched_at              TIMESTAMP,
    trades_fetched          INTEGER,
    date_first_trade        TIMESTAMP,
    date_last_trade         TIMESTAMP,
    active_days             INTEGER,
    is_lp                   BOOLEAN,
    is_hft_burst            BOOLEAN,
    peak_trades_per_15min   INTEGER,
    burst_trade_pct         NUMERIC(5,2),  -- PIPE-051
    top_market_trade_count  INTEGER,
    top_market_vol_pct      NUMERIC(5,2),
    filter_reason           VARCHAR(128),
    roundtrips_total        INTEGER,
    roundtrips_closed       INTEGER,
    roundtrips_open         INTEGER,
    wins                    INTEGER,
    losses                  INTEGER,
    win_rate                NUMERIC(5,4),
    calc_pnl_usd            NUMERIC(20,2),
    pnl_calc_method         VARCHAR(32),
    is_copyable             BOOLEAN,
    approved_for_tracking   BOOLEAN DEFAULT FALSE,
    reviewed_at             TIMESTAMP,
    notes                   TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_lc_wallet   ON leaderboard_candidates(wallet_address);
CREATE INDEX idx_lc_copyable ON leaderboard_candidates(is_copyable) WHERE is_copyable = TRUE;
CREATE INDEX idx_lc_approved ON leaderboard_candidates(approved_for_tracking) WHERE approved_for_tracking = TRUE;
```

### DDL — `leaderboard_candidate_trades`

```sql
CREATE TABLE leaderboard_candidate_trades (
    id             SERIAL PRIMARY KEY,
    wallet_address VARCHAR(66)   NOT NULL,
    tx_hash        VARCHAR(128),
    market_id      VARCHAR(128)  NOT NULL,
    outcome        VARCHAR(128),
    side           VARCHAR(4)    NOT NULL,
    size_usd       NUMERIC(20,2) NOT NULL,
    price          NUMERIC(10,6) NOT NULL,
    traded_at      TIMESTAMP     NOT NULL,
    created_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    UNIQUE(tx_hash)
);
CREATE INDEX idx_lct_wallet        ON leaderboard_candidate_trades(wallet_address);
CREATE INDEX idx_lct_wallet_market ON leaderboard_candidate_trades(wallet_address, market_id);
CREATE INDEX idx_lct_traded_at     ON leaderboard_candidate_trades(traded_at);
```

### DDL — `leaderboard_candidate_roundtrips`

```sql
CREATE TABLE leaderboard_candidate_roundtrips (
    id             SERIAL PRIMARY KEY,
    wallet_address VARCHAR(66)   NOT NULL,
    market_id      VARCHAR(128)  NOT NULL,
    outcome        VARCHAR(128),
    open_side      VARCHAR(4),
    open_size_usd  NUMERIC(20,2),
    open_price     NUMERIC(10,6),
    opened_at      TIMESTAMP,
    close_side     VARCHAR(4),
    close_size_usd NUMERIC(20,2),
    close_price    NUMERIC(10,6),
    closed_at      TIMESTAMP,
    close_type     VARCHAR(32),
    gross_pnl_usd  NUMERIC(20,2),
    net_pnl_usd    NUMERIC(20,2),
    pnl_status     VARCHAR(16),
    status         VARCHAR(16)   NOT NULL DEFAULT 'OPEN',
    created_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    UNIQUE(wallet_address, market_id, outcome)
);
CREATE INDEX idx_lcr_wallet        ON leaderboard_candidate_roundtrips(wallet_address);
CREATE INDEX idx_lcr_status        ON leaderboard_candidate_roundtrips(status);
CREATE INDEX idx_lcr_wallet_status ON leaderboard_candidate_roundtrips(wallet_address, status);
```

**Отличия от `whale_trade_roundtrips`:** нет `position_key`, `whale_id`, `open_trade_id`/`close_trade_id`, `market_title`/`market_category`, `matching_method`/`matching_confidence`, `fees_usd`. UNIQUE-ключ — `(wallet_address, market_id, outcome)` вместо `position_key`.

**NULL-guard (PIPE-050):** В `score_leaderboard_candidates.py` добавлены проверки `close_price IS NULL` и `open_price IS NULL` — группа с NULL-ценой переводится в `status=OPEN`, `pnl_status="OPEN"`, `gross_pnl=net_pnl=NULL`. Root cause: SELL-группы с `size_usd=0` дают `NULLIF(0,0)=NULL` в weighted average. Паттерн согласован с веткой `sell_count==0`.

---

## 10. Условия успеха / неуспеха

| Условие | Следствие |
|---------|-----------|
| `DATABASE_URL` не задан | `sys.exit(1)` |
| Leaderboard API недоступен | `main()` прерывается, таблицы без изменений |
| CLOB API недоступен (settlement) | `close_type='OPEN'`, P&L = NULL; скрипт продолжает |
| Нет кандидатов с `is_copyable IS NULL` | `score_leaderboard_candidates.py` завершается без обработки |

---

## 11. Зависимости

**Upstream:** `data-api.polymarket.com/v1/leaderboard`, `data-api.polymarket.com/activity`, `https://clob.polymarket.com/markets`, PostgreSQL.

**Production isolation:**

| Таблица | Затрагивается? |
|---------|---------------|
| `whales` | **НЕТ** |
| `whale_trades` | **НЕТ** |
| `whale_trade_roundtrips` | **НЕТ** |
| `paper_trades` | **НЕТ** |

**Downstream:** после `approved_for_tracking = TRUE` + `WHALE_STATUS_TRANSITIONS.md` → `UPDATE whales SET copy_status = 'tracked'` → `_tracked_poll_loop` (Шаг 1) → стандартная магистраль. Leaderboard pipeline на этом завершает роль.

---

## 12. Наблюдаемость

Оба скрипта логируют через `print()`. Heartbeat-файл отсутствует.

```sql
-- Состояние воронки
SELECT COUNT(*)                                      AS total,
       COUNT(*) FILTER (WHERE is_lp = TRUE)          AS lp_filtered,
       COUNT(*) FILTER (WHERE is_hft_burst = TRUE)   AS hft_flagged,
       COUNT(*) FILTER (WHERE approved_for_tracking) AS approved
FROM leaderboard_candidates;

-- Governance-таблица
SELECT wallet_address, username, leaderboard_rank,
       is_lp, is_hft_burst, peak_trades_per_15min,
       roundtrips_closed, win_rate, calc_pnl_usd
FROM leaderboard_candidates ORDER BY calc_pnl_usd DESC NULLS LAST;
```

---

## 13. RED FLAGs

### RF1 — Дублирование логики `roundtrip_builder.py` — технический долг

Зафиксировано в docstring `score_leaderboard_candidates.py`:
> `TODO: после завершения воронки — унифицировать с roundtrip_builder (параметризованный источник/назначение).`

Алгоритмы уже имеют архитектурное расхождение: scoring использует GROUP BY в одном SQL-запросе (одна позиция на `(wallet, market, outcome)`), `roundtrip_builder.py` — построчный INSERT через `ON CONFLICT` на `position_key`. Settlement дублируется в третьем месте — дополнительно к `roundtrip_builder.py` и `settle_resolved_positions()` (RF4).

### RF2 — `is_copyable = NULL` для всех: нет программного барьера для LP/HFT

Код `fetch_leaderboard_candidates.py:290–302` устанавливает `is_copyable = NULL` для всех кандидатов, включая LP и HFT. `score_leaderboard_candidates.py` также оставляет `is_copyable = NULL`. Ничто в коде не препятствует оператору установить `approved_for_tracking = TRUE` для кандидата с `is_lp = TRUE` или `is_hft_burst = TRUE`.

### RF3 — ЗАКРЫТО (PIPE-051, 2026-07-18): порог пересмотрен

Было: прогон 2026-06-08 — 9 `is_lp=TRUE`, 11 `is_hft_burst=TRUE` из 20, ни один не прошёл оба фильтра. Позже подтверждено на прогоне 2026-07-11: 41 из 43 кандидатов `is_hft_burst=TRUE`. Причина — единичный 15-минутный всплеск за всю 90-дневную историю флагал кандидата наравне с непрерывно торгующим ботом.

Фикс: новая метрика `burst_trade_pct` (доля 90-дневных сделок в окнах с count>20). Эмпирически на 13-24 живых кошельках — чистый разрыв: обычные трейдеры со случайным всплеском 0.97–31.25%, реальные боты 78.73–99.44%. Порог 50.0 в разрыве. Новое правило: `is_hft_burst = peak > 20 AND burst_trade_pct > 50.0`. На тестовой выборке 24 кошельков HFT-флаг снят с 16 из 22 ранее флагованных. Порог эмпирический на малой выборке — при накоплении данных подлежит перекалибровке.

### RF4 — Settlement через HTTP CLOB API, не через production SQL-механизм

`score_leaderboard_candidates.py:37`: `CLOB_API = "https://clob.polymarket.com/markets"`. Production-механизм `settle_resolved_positions()` (шаг 3B) не используется. Логика settlement присутствует в трёх местах: `roundtrip_builder.py`, `settle_resolved_positions()`, `score_leaderboard_candidates.py`. При изменении формата CLOB API или логики определения победителя — три места синхронизировать отдельно.

### RF5 — UNIQUE `(wallet, market, outcome)`: повторные позиции не моделируются

DDL `leaderboard_candidate_roundtrips`: `UNIQUE(wallet_address, market_id, outcome)`. Если кандидат открыл позицию, закрыл и открыл снова — второй цикл перезапишет первый через `ON CONFLICT DO UPDATE`. Ограничение по сравнению с `whale_trade_roundtrips`.

**Миграция 2026-07-11:** `scripts/migrations/pipe_049_leaderboard_categories.sql` — добавлены `best_category VARCHAR(32)` и `categories TEXT` в `leaderboard_candidates`. Поля заполняются в fetch: `best_category` = категория с максимальным `leaderboard_pnl_usd`; `categories` = CSV `CATEGORY:rank` для всех категорий кандидата.

---

## 14. Связь с основной магистралью

```
Leaderboard scoring pipeline
         │
         │  (изолирован, production-таблицы не затрагиваются)
         ▼
leaderboard_candidates ──► STRATEGY review
                                    │
                                    │  approved_for_tracking = TRUE
                                    │  + WHALE_STATUS_TRANSITIONS.md
                                    ▼
                           UPDATE whales SET copy_status = 'tracked'
                                    │
                                    ▼
                        ШАГ 1 — _tracked_poll_loop (targeted)
                        → ШАГ 2A/2B → ШАГ 3A/3B/3C → ШАГ 4 → ...
```

---

**Конец документа.**
