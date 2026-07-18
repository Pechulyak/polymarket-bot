# PIPELINE_MAP_L1 — paper→live copy (S1)

**Статус документа:** описание live-ветки, звено S1 (генерация intent-ордеров)
**Последняя верификация:** 2026-07-05 (весь документ сверен против живого DDL, кода и БД на S1; источники транспортных документов НЕ использованы как истина)
**Источник истины:** этот файл + `PIPELINE_MAP_L2_live_executor.md` (звено S2)
**Связь с магистралью:** live-ветка — sidebar, параллельный paper-ветке (P1–P4). Нумерация L1 (S1) → L2 (S2).

---

## 0. Что описывает L1

L1 — **первое звено live-исполнения**: путь от появления сделки live-кита в `whale_trades` до создания intent-записи в `live_orders` на S1. Дальше intent забирает демон S2 (см. L2).

Ключевое отличие от paper-ветки: paper-ветка заканчивается симуляцией P&L в matviews; live-ветка **производит реальный ордер** через тот же INSERT в `paper_trades`, но с последующим проталкиванием в `live_orders` → S2 → CLOB.

**Не путать с:**
- paper-веткой (P1–P4) — та же точка входа (`paper_trades`), но иной downstream
- L2 — исполнение intent на S2 (отдельный документ)

---

## 1. Карта звена L1

```
┌─────────────────────────────────────────────────────────────────┐
│ whale_trades (S1)                                                │
│ INSERT сделки live-кита (copy_status='live')                     │
│ Источник записи: whale_detector _fetch_paper_whale_trades        │
│   (30s-цикл, WHERE copy_status IN ('paper','live') — LIVE-007)   │
└───────────────────────────┬─────────────────────────────────────┘
                            │ AFTER INSERT FOR EACH ROW
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ TRIGGER trigger_copy_whale_trade                                 │
│ FUNCTION copy_whale_trade_to_paper()                             │
│   gate: whale.copy_status IN ('paper','live')                    │
│   → INSERT INTO paper_trades (Kelly sizing)                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ AFTER INSERT ON paper_trades
                            ├──────────────────────────────┐
                            ▼                              ▼
┌──────────────────────────────────┐   ┌──────────────────────────────────┐
│ TRIGGER trigger_notify_paper_    │   │ TRIGGER trigger_notify_paper_    │
│   trade → notify_paper_trade()   │   │   trade_to_live →                │
│ (Telegram-алерт, PIPE-048)       │   │   notify_paper_trade_to_live()   │
│ ── не L1, side-route             │   │ → pg_notify('live_copy', pt.id)  │
└──────────────────────────────────┘   └───────────────┬──────────────────┘
                                                        │ NOTIFY channel
                                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│ copy_paper_to_live.py (S1)                                       │
│   LISTEN mode (демон, systemd polymarket-copy-live-daemon)       │
│   OR --sweep (cron */15, flock, gap-fill 6h окно)                │
│   process_one(): 6 гейтов → INSERT live_orders (status='intent') │
└───────────────────────────┬─────────────────────────────────────┘
                            │ pull-model
                            ▼
                    live_orders (status='intent')
                    → забирает L2 (демон S2)
```

---

## 2. Роль звена в live-ветке

L1 превращает сделку live-кита в готовый к исполнению intent. Всё звено — на S1 (Польша, геоблок CLOB на запись), поэтому L1 **не исполняет** ордер, а только формирует его как строку `live_orders` для pull-модели. Реальная отправка — L2 (S2, egress на CLOB работает).

---

## 3. Исходные файлы (верифицировано 2026-07-05)

**Poller (вход в whale_trades):**
`src/research/whale_detector.py` — `_fetch_paper_whale_trades()`, SELECT `whale_detector.py:1682` (`WHERE copy_status IN ('paper','live')` после LIVE-007; до фикса — только `'paper'`, что и было root cause молчания live-кита).

**Триггер копирования:**
`copy_whale_trade_to_paper()` — PL/pgSQL функция в БД (не в git, определение только в `pg_get_functiondef`). Триггер `trigger_copy_whale_trade AFTER INSERT ON whale_trades`.

**Триггеры paper_trades:**
- `trigger_notify_paper_trade → notify_paper_trade()` — Telegram (PIPE-048), не L1
- `trigger_notify_paper_trade_to_live → notify_paper_trade_to_live()` → `pg_notify('live_copy', id)`

**Intent-генератор:**
`scripts/copy_paper_to_live.py` (440 строк, S1). Ключевые функции: `process_one()` (гейты + insert), `insert_live_order()`, `get_kill_switch()`, `listen_mode()`, `sweep_mode()`.

**systemd:** `/etc/systemd/system/polymarket-copy-live-daemon.service` (LISTEN, enabled, PID 2080 на момент верификации).

**cron:** root crontab S1 — sweep `*/15` под flock `/tmp/copy_live_sweep.lock`.

---

## 4. Инфраструктура

- **Сервер:** S1 (212.192.11.92), контейнер БД `polymarket_postgres` (порт 5433, DB `polymarket`).
- **Демон LISTEN:** systemd `polymarket-copy-live-daemon.service`, Restart=always.
- **Sweep:** cron `*/15`, one-shot, flock-защита от наложения.
- **Роль БД для L2-доступа:** `order_executor` (SELECT+UPDATE на `live_orders`, без INSERT/DELETE).

---

## 5. Триггеры запуска и расписание

| Механизм | Тип | Расписание | Роль |
|----------|-----|------------|------|
| DB-триггер `trigger_copy_whale_trade` | синхронный | на каждый INSERT в whale_trades | создаёт paper_trades |
| DB-триггер `trigger_notify_paper_trade_to_live` | синхронный | на каждый INSERT в paper_trades | pg_notify('live_copy') |
| `copy_paper_to_live.py` LISTEN | демон | постоянный, реагирует на NOTIFY | intent из notify |
| `copy_paper_to_live.py --sweep` | cron | `*/15` | gap-fill за 6h окно (пропущенные notify) |

Два пути к intent (LISTEN + sweep) идемпотентны через `ON CONFLICT (idempotency_key) DO NOTHING`, ключ `pt_<paper_trade_id>`.

---

## 6. Алгоритм звена

### 6.1 whale_trades INSERT (вход)

`_fetch_paper_whale_trades()` (30s-цикл) выбирает китов `copy_status IN ('paper','live')`, тянет сделки через `/activity`, пишет в `whale_trades` с `source='PAPER_TRACK'` и заполненным `whale_id` (верифицировано: live-кит 0x033f0346 имеет `whale_id=117143` в существующих строках). CHECK на `source` включает `PAPER_TRACK` — live-кит проходит той же веткой.

### 6.2 copy_whale_trade_to_paper() (триггер, точное поведение из DDL)

1. `SELECT wallet_address, COALESCE(estimated_capital, 100000) FROM whales WHERE id = NEW.whale_id` → если `whale_id` NULL, `v_whale_address` = NULL, функция дойдёт до финального `RETURN NEW` без вставки.
2. Kelly-параметры из `strategy_config` (kelly_bankroll_source, our_bankroll/current_balance, kelly_fraction, max_position_pct, min_trade_size, min_whale_trade_pct, max_entry_price) с дефолтами.
3. Гейт: `EXISTS (SELECT 1 FROM whales WHERE wallet_address=v_whale_address AND copy_status IN ('paper','live'))` → `v_is_top_whale`. Комментарий в коде: «LIVE-004: extended to include 'live' whales».
4. Если `v_is_top_whale`:
   - дедуп: EXISTS paper_trades с тем же tx_hash+wallet за 5 минут → RETURN NEW;
   - `v_whale_pct = size_usd / whale_capital`; если `< min_whale_trade_pct` → RETURN NEW;
   - если `price > max_entry_price` → RETURN NEW;
   - Kelly: `v_our_size = whale_pct × our_bankroll × kelly_fraction`; `v_kelly_size = GREATEST(min_trade_size, LEAST(our_size, our_bankroll × max_position_pct))`;
   - INSERT INTO paper_trades (включая `token_id = NEW.token_id`, LIVE-004).

Ключевой факт: гейт `IN ('paper','live')` **уже** пропускает live-кита. Разрыв до LIVE-007 был не здесь, а выше — в poller, который не наполнял whale_trades для live.

### 6.3 notify_paper_trade_to_live() (триггер → NOTIFY)

AFTER INSERT ON paper_trades → `pg_notify('live_copy', paper_trade_id)`. (Тело функции не дампилось в этой сессии — DDL-верификация функции остаётся открытым пунктом, см. §16.)

### 6.4 process_one() в copy_paper_to_live.py (6 гейтов, из полного файла)

1. **Gate 1 — kill-switch:** свежий `SELECT value FROM strategy_config WHERE key='live_whale_copy'`, без кэша. `!= 1.0` → skip.
2. Fetch `paper_trades` JOIN `whales` по `wallet_address` (не по whale_id) с `copy_status`.
3. **Gate 2 — copy_status:** `!= 'live'` → skip. **Здесь live обязателен** (в отличие от триггера, где `IN paper,live`). Live-кит проходит, paper-кит отсекается — live_orders создаётся только для live.
4. **Gate 2b — side (LIVE-009):** `side.upper() != 'BUY'` → skip, intent не создаётся. Executor BUY-only; SELL блокируется до очереди (второй слой — guard в executor). Долг: LIVE-010.
5. **Gate 3 — kelly_size:** `<= 0` → skip.
6. **Gate 4 — token_id:** NULL/пусто → skip (fail-closed для исторических/категориальных сделок).
7. **Gate 5 — дедуп позиции (LIVE-008):** `has_live_intent_for_position()` — та же позиция (whale+market+outcome+side+price) в окне 6ч уже имеет не-failed/rejected intent → skip.
8. `insert_live_order()`: INSERT в `live_orders` (token_id, condition_id=market_id, market_title, outcome, side=UPPER, size_usd=kelly_size, idempotency_key=`pt_<id>`, status='intent'), `ON CONFLICT (idempotency_key) DO NOTHING`.

### 6.5 sweep_mode() (cron fallback)

Kill-switch на входе (off → exit 0). SELECT кандидатов: `paper_trades JOIN whales (copy_status='live') LEFT JOIN live_orders (idempotency_key='pt_'||id) WHERE kelly_size>0 AND token_id IS NOT NULL AND created_at >= now()-6h AND live_orders.id IS NULL`. Каждый → `process_one()`. Идемпотентно.

---

## 7. Kill-switch

`strategy_config.live_whale_copy`. Значение на момент верификации: `1.00000000` (ENABLED). Читается свежим SELECT в каждом `process_one()` и на входе sweep. `!= 1.0` → intent не создаётся. Единая точка остановки live-копирования без остановки демона.

---

## 8. live_orders — структура (верифицировано \d+)

Колонки: id, token_id, condition_id, market_title, outcome, side, size_usd, limit_price, status, idempotency_key, clob_order_id, filled_size, error, created_at, updated_at, claimed_at, route.

Индексы: pkey(id); `idx_live_orders_intent` (partial, status='intent'); unique(idempotency_key).

CHECK: limit_price∈(0,1); side∈{BUY,SELL}; size_usd>0; status∈{intent,claimed,submitted,filled,partial,rejected,failed}.

GRANT `order_executor`: SELECT, UPDATE (без INSERT/DELETE — вставляет только L1, обновляет только L2).

---

## 9. Условия успеха / неуспеха

| Исход | Условие | Поведение |
|-------|---------|-----------|
| intent создан | все 4 гейта пройдены, нет конфликта | строка live_orders status='intent', L2 подхватит |
| дубликат | idempotency_key существует | ON CONFLICT DO NOTHING, `inserted=False`, лог «already exists» |
| kill-switch off | live_whale_copy != 1 | skip, лог, intent НЕ создан |
| не-live кит | copy_status != 'live' | skip (Gate 2) |
| NULL token_id | token_id пусто | skip (Gate 4, fail-closed), лог ERROR |
| whale_id NULL в whale_trades | триггер не находит адрес | paper_trade НЕ создаётся, вся цепь молчит |

---

## 10. Зависимости

**Upstream:** poller `_fetch_paper_whale_trades` (LIVE-007) — без него whale_trades для live-кита пусты, вся L1-цепь не стартует. Это и был единственный разрыв (2026-07-01…07-05).

**Downstream:** L2 (демон S2) читает `live_orders` status='intent' по pull-модели через роль `order_executor`.

**Конфиг:** `strategy_config` (kill-switch, Kelly-параметры). `whales.estimated_capital` (Kelly base).

---

## 13. Особые случаи и риски (RED FLAGs)

**RED FLAG #1 — Асимметрия гейтов trigger vs copy-to-live.** Триггер `copy_whale_trade_to_paper` пропускает `IN ('paper','live')`, а `process_one` Gate 2 требует строго `='live'`. Следствие: paper-кит создаёт paper_trades, но НЕ доходит до live_orders (корректно). Live-кит проходит оба. Асимметрия намеренная, но не документирована в самих функциях — источник путаницы при ревью.

**RED FLAG #2 — whale_id как единственный вход триггера.** `copy_whale_trade_to_paper` стартует с `WHERE w.id = NEW.whale_id`. Если poller запишет whale_trades с `whale_id=NULL`, триггер молча ничего не сделает (RETURN NEW без вставки). Верифицировано, что live-кит имеет whale_id заполненным, но гарантии на уровне схемы нет (колонка nullable). Регрессия в save-пути обрушит всю L1-цепь без ошибок.

**RED FLAG #3 — Живёт связанный дефект в 2A (RED FLAG #5).** `_known_whales` в whale_detector грузится только для `qualification_status IN ('qualified','ranked','tracked')` — `live` не в наборе. Прямого эффекта на L1 нет (copy_status ≠ qualification_status), но при обнаружении live-кита логи «new vs updated» дезориентируют. Отдельный тикет.

**RED FLAG #4 — Две matview (paper P&L) не фильтруют copy_status.** `paper_simulation_pnl`, `paper_portfolio_state` join по market_id/wallet/side/outcome без фильтра статуса → сделки live-кита учитываются в paper-метриках. По решению оператора (2026-07-05) — это by design (live-кит отображается в paper). Зафиксировано, чтобы будущий читатель не принял за баг.

**RED FLAG #5 — last_targeted_fetch_at застрял.** У live-кита `last_targeted_fetch_at=2026-04-04` при фактических сделках до 07-01. Баг апдейта тайминга в save-пути, к обрыву L1 отношения не имеет (fetch не использует это поле как гейт для paper-ветки). Отдельный тикет.

**RED FLAG #6 — sweep-окно 6h vs cron 15min.** Sweep смотрит назад 6h, cron бежит каждые 15 мин. При простое демона >6h часть notify будет потеряна безвозвратно (LISTEN пропустил, sweep не достаёт за окном). Для редких live-сделок риск низкий, но не нулевой.

---

## 14. Результат звена

После L1: для каждой сделки live-кита (прошедшей Kelly/цена/token гейты) существует строка `live_orders` status='intent', готовая к pull-исполнению на S2. Без L1 live-кит не производит ни paper-симуляции, ни live-ордера.

---

## 15. Краткая бизнес-формула звена

```
ВХОД: whale_trades INSERT (live-кит, copy_status='live', whale_id заполнен)
  │
  ├── TRIGGER copy_whale_trade_to_paper (AFTER INSERT)
  │   ├── SELECT whale по NEW.whale_id → v_whale_address (NULL → выход)
  │   ├── gate: copy_status IN ('paper','live') → v_is_top_whale
  │   ├── дедуп 5мин / min_whale_pct / max_entry_price гейты
  │   ├── Kelly sizing (strategy_config)
  │   └── INSERT paper_trades (+ token_id)
  │
  ├── TRIGGER notify_paper_trade_to_live (AFTER INSERT ON paper_trades)
  │   └── pg_notify('live_copy', paper_trade_id)
  │
  ├── copy_paper_to_live.py LISTEN (или --sweep cron */15)
  │   └── process_one(trade_id):
  │       ├── Gate 1: kill-switch live_whale_copy == 1 (свежий read)
  │       ├── Gate 2: whale.copy_status == 'live'   ← live обязателен
  │       ├── Gate 3: kelly_size > 0
  │       ├── Gate 4: token_id NOT NULL (fail-closed)
  │       └── INSERT live_orders (status='intent', idem=pt_<id>, ON CONFLICT DO NOTHING)
  │
ВЫХОД: live_orders (status='intent') → pull L2 (S2)
```

---

## 16. Открытые вопросы

- Тело `notify_paper_trade_to_live()` не дампилось в сессии верификации — точная логика pg_notify (payload=id? условия?) остаётся к подтверждению через `pg_get_functiondef` перед финализацией.
- Kelly-путь при `kelly_bankroll_source=1` читает `current_balance` из `paper_portfolio_state` — для live-кита это смешивает paper-баланс в live-сайзинг. Семантика при живых деньгах требует ревью (сейчас STAGE, FIXED_ORDER_USD на стороне S2 перекрывает — см. L2).
- STAGE-режим: L2 использует FIXED_ORDER_USD=$1, поэтому `size_usd` из intent на S2 может игнорироваться. Точка стыковки L1.size_usd ↔ L2.FIXED_ORDER_USD — уточнить в L2.
