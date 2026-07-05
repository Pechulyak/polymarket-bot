# PIPELINE_MAP_L2 — live_executor_daemon (S2)

**Статус документа:** описание live-ветки, звено S2 (исполнение intent на CLOB)
**Последняя верификация:** 2026-07-05 (структура сверена против git-копии `executor/live_executor_daemon.py`; ⚠️ боевой демон на S2 правился вне git — LIVE-003/006 — поэтому пункты с пометкой [S2-VERIFY] требуют сверки с `/opt/executor/app/live_executor_daemon.py` на живом S2 перед финализацией)
**Источник истины:** этот файл + `PIPELINE_MAP_L1_paper_to_live.md` (звено S1)
**Связь с магистралью:** L2 — второе звено live-ветки, потребитель `live_orders` (status='intent') из L1.

> ⚠️ **LIVE-006 caveat:** код демона на S2 живёт в `/opt/executor/app/`, коммитится копированием в `executor/` (может отставать). Известные вне-git правки: LIVE-003 (filled_size taker, route column). Все [S2-VERIFY] пункты ниже — из git-копии, НЕ подтверждены на живом S2 в этой сессии.

---

## 0. Что описывает L2

L2 — **исполнение**: демон на S2 забирает intent-ордер из `live_orders`, проверяет баланс, выбирает maker/taker путь, отправляет ордер на CLOB, отслеживает fill, пишет результат обратно в `live_orders`. S2 (62.60.233.100) — единственный сервер с рабочим egress на Polymarket CLOB (S1 геоблокирован).

**Не путать с:**
- L1 (S1) — генерация intent (отдельный документ)
- `executor.py` — устаревший single-shot stub (docstring 2026-06-14, live заблокирован багом #64/#70); НЕ боевой путь. Боевой = `live_executor_daemon.py`.

---

## 1. Карта звена L2

```
live_orders (status='intent')  ◄── L1 (S1)
        │ pull-model, роль order_executor (SELECT+UPDATE)
        ▼
┌─────────────────────────────────────────────────────────────┐
│ live_executor_daemon.py (S2), systemd live-executor.service  │
│ main loop, POLL_INTERVAL=10s                                 │
│                                                             │
│  claim_intent()                                             │
│    SELECT status='intent' ORDER BY created_at LIMIT 1       │
│    UPDATE → status='claimed' WHERE status='intent' (атомарно)│
│        │                                                    │
│        ▼                                                    │
│  get_order_book(token_id)                                   │
│    best_bid, best_ask, neg_risk, min_order_size             │
│    гейты: empty_orderbook / crossed_book → failed           │
│        │                                                    │
│        ▼                                                    │
│  BALANCE GATE: on-chain pUSD balanceOf(FUNDER)              │
│    < FIXED_ORDER_USD+0.05 → failed                          │
│        │                                                    │
│        ▼                                                    │
│  ROUTING: shares_maker = FIXED_ORDER_USD / best_bid         │
│    ├── >= min_order_size → MAKER (GTC @ best_bid)           │
│    │     monitor_order 15min → matched=filled               │
│    │     timeout → cancel → taker_fallback                  │
│    └── < min_order_size → TAKER (FOK) прямо                 │
│        │                                                    │
│        ▼                                                    │
│  set_status → live_orders (filled/failed/submitted)         │
│    + clob_order_id, route, filled_size                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Роль звена в live-ветке

L2 — точка, где abstract intent становится реальным ордером и реальной экспозицией. Всё, что до L2 (whale_trades → paper_trades → live_orders), — подготовка; L2 двигает деньги. Поэтому здесь сосредоточены защитные гейты: on-chain balance, STAGE-режим FIXED_ORDER_USD=$1, one-shot логика (упал — failed, без автоповтора внутри тика).

---

## 3. Исходные файлы

**Боевой демон:** `/opt/executor/app/live_executor_daemon.py` (S2). Git-копия: `executor/live_executor_daemon.py` (406 строк в копии; [S2-VERIFY] точное число строк на S2).

Ключевые функции (из git-копии): `build_client()`, `get_db_conn()`, `claim_intent()`, `set_status()`, `get_onchain_pusd_balance()`, `submit_taker()`, `monitor_order()`, `main()`.

**Устаревший stub (НЕ боевой):** `executor.py` — single-shot diag/dry/live, заблокирован #64/#70. Не входит в L2-путь.

**Секреты (S2):** `/opt/executor/secrets/.signer_key` (EOA-ключ, 600 root). DATABASE_URL через systemd LoadCredential (LIVE-002).

---

## 4. Инфраструктура

- **Сервер:** S2 (62.60.233.100), Ubuntu 22.04, egress CLOB ~169ms (не геоблок).
- **systemd:** `live-executor.service` (LIVE-002): LoadCredential для DATABASE_URL, Restart=on-failure/RestartSec=30, MemoryHigh=200M/MemoryMax=350M. [S2-VERIFY] текущий PID/uptime.
- **Клиент:** `py_clob_client_v2`, venv `/opt/executor/app/venv`. Аккаунт: funder `0x3fC83D2b40F9f243Cbcd51a53cFdd7E9A6D366a1`, sig3/POLY_1271.
- **Конфиг (git-копия, hardcoded):** POLL_INTERVAL=10s, FILL_POLL_INTERVAL=30s, MAKER_TIMEOUT_MINUTES=15, FIXED_ORDER_USD=1.0 (STAGE).

---

## 5. Триггер запуска и расписание

Единственный триггер — `main()` loop, `POLL_INTERVAL=10s`. Демон постоянный (systemd), не cron. На каждой итерации: один claim (LIMIT 1), полная обработка, следующий тик. Нет параллелизма — ордера исполняются последовательно.

---

## 6. Алгоритм звена (из git-копии)

### 6.1 claim_intent() — атомарный захват

`SELECT id,token_id,condition_id,outcome,side,size_usd,idempotency_key FROM live_orders WHERE status='intent' ORDER BY created_at LIMIT 1`, затем `UPDATE status='claimed' WHERE id=%s AND status='intent' RETURNING id`. Если RETURNING пусто — другой процесс уже захватил, skip. Претендует на роль pull-модели: несколько демонов безопасны (претендует — [S2-VERIFY], но на практике один демон).

### 6.2 Книга и гейты

`get_order_book(token_id)`: `best_bid=max(bids)`, `best_ask=min(asks)`. Гейты → status='failed': пустой `bids` (empty_orderbook); `best_bid >= best_ask` (crossed_book). `neg_risk` и `min_order_size` берутся из книги (не hardcoded).

### 6.3 BALANCE GATE (on-chain)

`get_onchain_pusd_balance()`: ERC-20 `balanceOf(FUNDER)` через `eth_call`, селектор `0x70a08231`, fallback по RPC_URLS (drpc/publicnode/1rpc), fail-closed если все RPC мертвы. Порог: `FIXED_ORDER_USD + 0.05 = 1.05`. `< 1.05` → status='failed'. Замечание из memory: `get_balance_allowance()` SDK всегда 0, поэтому on-chain balanceOf — единственный корректный источник.

### 6.4 ROUTING maker/taker

`shares_maker = FIXED_ORDER_USD / best_bid`.
- `shares_maker >= min_order_size` → **MAKER**: `OrderArgsV2(price=best_bid, size=shares, side)`, `post_order(GTC)`, status='submitted' + clob_order_id + limit_price. Затем `monitor_order` 15 мин: `get_order(order_id)`, `status=='matched'` → filled. Timeout → `cancel_order` → `submit_taker(tag='taker_fallback')`.
- `shares_maker < min_order_size` → **TAKER прямо**: `submit_taker(tag='taker_direct')`, без 15-мин ожидания.

### 6.5 submit_taker() — FOK market BUY

`MarketOrderArgsV2(token_id, amount=size_usd, side=BUY)`, `create_market_order`, `post_order(FOK)`. `success and status=='matched'` → filled + clob_order_id + error=tag (route). Иначе → failed + errorMsg. [S2-VERIFY] LIVE-003 добавил `filled_size` из `resp.takingAmount` и колонку `route` — в git-копии `submit_taker` пишет tag в поле `error` (семантика route через error), но LIVE-003 changelog говорит о раздельных колонках error/route и filled_size из takingAmount. **Расхождение git-копии и changelog — обязательная сверка с S2.**

### 6.6 set_status() — запись результата

`UPDATE live_orders SET status,error,updated_at + extra (clob_order_id/limit_price/filled_size) WHERE id`. Роль order_executor имеет UPDATE — запись результата разрешена.

---

## 7. STAGE-режим (защита на этапе обкатки)

FIXED_ORDER_USD=$1.0 — фиксированный размер ордера, **игнорирует `size_usd` из intent** (комментарий в коде: «size_usd из БД не используется ни для суммы, ни для routing»). Это разрывает Kelly-сайзинг L1: сколько бы L1 ни насчитал в `size_usd`, L2 в STAGE ставит $1. Снятие STAGE + возврат Kelly (LIVE-005) блокировано синхронизацией `our_bankroll=$300` конфига с on-chain балансом. Это точка стыковки L1.size_usd ↔ L2.FIXED_ORDER_USD (открытый вопрос L1 §16).

---

## 8. live_orders — колонки, пишущиеся L2

Читает: token_id, condition_id, outcome, side, size_usd (игнорирует в STAGE). Пишет: status (claimed→submitted→filled/failed), clob_order_id, limit_price (maker), filled_size [S2-VERIFY LIVE-003], route [S2-VERIFY LIVE-003], error, updated_at, claimed_at. GRANT order_executor: SELECT+UPDATE (INSERT/DELETE нет — вставляет L1).

---

## 9. Условия успеха / неуспеха

| Исход | Условие | status |
|-------|---------|--------|
| filled (taker) | FOK matched | filled + route=taker_direct/taker_fallback |
| filled (maker) | GTC matched в 15 мин | filled |
| submitted→timeout | maker не исполнился 15 мин | cancel → taker_fallback |
| empty_orderbook | нет bids | failed |
| crossed_book | best_bid≥best_ask | failed |
| balance gate | on-chain < 1.05 | failed |
| RPC fail | все RPC мертвы | failed (balance_rpc_error) |
| FOK not matched | taker не свёлся | failed |

---

## 10. Зависимости

**Upstream:** L1 — `live_orders` status='intent'. Без intent демон крутит пустой claim каждые 10с.

**External:** Polymarket CLOB (post_order, get_order, get_order_book, cancel_order, get_tick_size); RPC-ноды Polygon (balanceOf); on-chain pUSD контракт `0xC011...E82DFB`.

**Конфиг:** FIXED_ORDER_USD (STAGE), MAKER_TIMEOUT_MINUTES. `.signer_key` на S2.

**Мониторинг:** INFRA-046 (heartbeat-alert live_executor в pipeline_monitor, порог 120s); INFRA-047 (stuck-orders watchdog: intent/claimed/submitted >120s).

---

## 13. Особые случаи и риски (RED FLAGs)

**RED FLAG #1 — [S2-VERIFY] git-копия vs боевой S2.** LIVE-003 (filled_size, route) правился вне git. Git-копия может не отражать боевую логику записи filled_size/route. Весь §6.5/§8 в части этих колонок — под сверку с `/opt/executor/app/live_executor_daemon.py`.

**RED FLAG #2 — STAGE рвёт Kelly.** FIXED_ORDER_USD=$1 игнорирует size_usd. Пока STAGE — L1-сайзинг декоративен. При снятии STAGE без ревью L1 Kelly-пути (paper_portfolio_state как bankroll source для live) размер может оказаться некорректным.

**RED FLAG #3 — one-shot без ретрая на failed.** Ордер в status='failed' не переretryится демоном. Требует ручного вмешательства или sweep-логики (которой в L2 нет). Intent, упавший на транзиентной ошибке (RPC-глюк прошёл gate, но CLOB 5xx), останется failed.

**RED FLAG #4 — claimed без завершения = зависание.** Если демон падёт между claim (status='claimed') и set_status, ордер застрянет в 'claimed'. INFRA-047 watchdog это ловит (алерт >120s), но авто-recovery нет — claimed не возвращается в intent.

**RED FLAG #5 — последовательное исполнение.** LIMIT 1 + один демон = ордера строго по очереди. При всплеске intent (несколько live-сделок разом) обработка сериализуется по 10с+book+balance+15min-maker. Задержка исполнения на волатильном рынке = adverse selection.

**RED FLAG #6 — maker fallback удваивает время.** Maker-путь: 15 мин ожидания → cancel → taker. Худший случай — 15 мин на неисполнимом лимите, потом taker по уехавшей цене. Для копирования directional-кита (hold-to-settlement) терпимо, но структурно медленно.

**RED FLAG #7 — RAM S2 критична.** Memory из инфры: S2 ~342MB free, swap=0, MemoryMax=350M на юните. Демон под жёстким лимитом; OOM-kill возможен, тогда Restart=on-failure поднимет, но claimed-ордер зависнет (RF#4).

---

## 14. Результат звена

После L2: intent-ордер исполнен на CLOB (filled) либо помечен failed с причиной. Реальная позиция открыта на funder-кошельке. filled_size (при корректной записи) даёт фактический исполненный объём для downstream-учёта.

---

## 15. Краткая бизнес-формула звена

```
ВХОД: live_orders status='intent' (из L1)
  │
  ├── main loop (10s):
  │   claim_intent() → status='claimed' (атомарный UPDATE ... WHERE status='intent')
  │       │ пусто → sleep 10s
  │       ▼
  │   get_order_book(token_id)
  │       ├── empty bids → failed(empty_orderbook)
  │       ├── best_bid≥best_ask → failed(crossed_book)
  │       ▼
  │   BALANCE GATE: on-chain balanceOf(FUNDER)
  │       └── < FIXED_ORDER_USD+0.05 → failed(insufficient)
  │       ▼
  │   shares_maker = FIXED_ORDER_USD / best_bid
  │       ├── >= min_order_size → MAKER GTC @ best_bid
  │       │     status='submitted' → monitor_order 15min
  │       │       ├── matched → filled
  │       │       └── timeout → cancel → submit_taker(taker_fallback)
  │       └── < min_order_size → submit_taker(taker_direct) FOK
  │       ▼
  │   set_status → live_orders (filled/failed + clob_order_id, route, filled_size)
  │
ВЫХОД: реальная позиция на CLOB + live_orders в терминальном статусе
```

---

## 16. Открытые вопросы (обязательны к закрытию перед финализацией L2)

1. **[S2-VERIFY] Сверка боевого демона.** Прочитать `/opt/executor/app/live_executor_daemon.py` на живом S2, diff против git-копии `executor/live_executor_daemon.py`. Особо: LIVE-003 filled_size (`resp.takingAmount`) и колонка route — как реально пишутся (git-копия использует поле error для tag, changelog говорит о раздельных колонках).
2. **[S2-VERIFY] systemd-статус.** `systemctl status live-executor.service`: active/PID/uptime/RestartCount на S2.
3. **maker filled_size (INFRA-049).** По memory заблокировано отсутствием боевого maker-fill; git-копия maker-пути пишет только status='filled' без filled_size. Подтвердить на S2.
4. **Idempotency при повторном intent.** L1 гарантирует уникальность intent через idempotency_key, но L2 не проверяет idempotency_key при исполнении — если один и тот же intent как-то попадёт дважды в 'intent', claim захватит оба. Оценить.
5. **STAGE→Kelly переход.** Точная процедура снятия FIXED_ORDER_USD и синхронизации our_bankroll=$300 с on-chain (блокер LIVE-005).
