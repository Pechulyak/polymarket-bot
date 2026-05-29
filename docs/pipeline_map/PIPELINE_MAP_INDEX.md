# PIPELINE_MAP_INDEX

**Статус документа:** обязательное первое чтение для любого чата, работающего над pipeline_map
**Последнее обновление:** 2026-05-28 (шаг 3C `close_sell` переведён в ACTIVE по итогам аудита: host-cron `15 * * * *` запускает `python3 -m src.strategy.roundtrip_builder --close`, реактивация выполнена TRD-443; добавлен шаг 9 paper-ветки — три materialized view paper P&L, финальный шаг ветки; магистраль 6/6 + paper 3/3 описаны, P3 — NOT-PRESENT)
**Источник истины о магистрали сделки:** этот файл + связанные `PIPELINE_MAP_*.md`

---

## 0. Что такое pipeline_map

Pipeline_map — это карта **магистрального пути одной сделки** кита от момента её обнаружения через внешний Polymarket Data API до достижения сделкой финального состояния в системе. Документ описывает state-изменения сделки и точки ветвления магистрали; не описывает каждый компонент кода.

**Не путать с:**
- Картой зависимостей кода (для этого — `AGENTS.md`, README)
- PROJECT_STATE (только текущее состояние системы, без логики потока)
- Аудитом производительности или безопасности (это отдельные задачи)

Правила формата шагов, метод определения следующего шага, обязательные первые действия нового чата — в context transfer документе `DOC-PIPELINE-MAP`. RED FLAG'и каждого шага — в §13 соответствующего файла шага.

---

## 1. Карта магистрали целиком

```
                ┌─────────────────────────────────────┐
                │ Polymarket Data API                 │
                │ data-api.polymarket.com             │
                └──────────────┬──────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ШАГ 1 — read_api                                                     │
│ Контейнер whale-detector, discovery-цикл (60s) — магистраль          │
│ Получение List[TradeWithAddress], read-only                          │
│                                                                      │
│ Параллельно (сбор данных, не магистраль):                            │
│   paper-цикл (30s), tracked-цикл (300s),                             │
│   HOT-цикл (4h), WARM-цикл (24h)                                     │
│   — polling уже известных китов, пишут в whale_trades через 2B,      │
│     но не открывают магистраль для новой сделки                      │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
       ВЕТВЛЕНИЕ ШАГА 2: per-address и per-trade ветки идут параллельно
       в рамках одной итерации discovery-цикла _polymarket_poll_loop
               │
      ┌────────┴────────┐
      ▼                 ▼
┌─────────────┐   ┌─────────────────────────────────────────────────┐
│ ШАГ 2A      │   │ ШАГ 2B — whale_trades_write                     │
│ whale_      │   │ WhaleTradesRepo.save_trade()                    │
│ registration│   │ INSERT в whale_trades                            │
│ Только      │   │ Дедупликация по tx_hash (только если передан)   │
│ discovery   │   │ whale_id = NULL для нерегистрированных          │
│ INSERT ON   │   │                                                 │
│ CONFLICT в  │   │ session.commit() ──┐                            │
│ whales      │   │                    │                            │
└─────────────┘   └────────────────────┼────────────────────────────┘
                                       │
                                       ▼
                            СИНХРОННАЯ ТОЧКА ВЕТВЛЕНИЯ
                            (управляется whales.copy_status)
                                       │
                          ┌────────────┴────────────┐
                          ▼                         ▼
            copy_status = 'none'/'tracked'   copy_status = 'paper'
            (большинство китов)              (отобранные оператором)
                          │                         │
                          │                         ▼
                          │              [PAPER-ВЕТКА — sidebar]
                          │              DB-trigger trigger_copy_whale_trade
                          │              INSERT в paper_trades с Kelly sizing
                          │              → дальнейший paper-pipeline:
                          │                notifications, settlement и т.д.
                          │                (нумерация P1, P2... — отдельно)
                          ▼
            ┌──────────────────────────────────────────────────┐
            │ ШАГ 3A — roundtrip_open (ACTIVE)                │
            │ Контейнер roundtrip_builder, while-loop 2h       │
            │ run(rebuild=False) без CLI-флагов                │
            │ BUY-сделки → агрегация (wallet, market, outcome) │
            │ INSERT OPEN в whale_trade_roundtrips             │
            │ ON CONFLICT (position_key) DO NOTHING            │
            └──────────────────────┬───────────────────────────┘
                                   │
                                   ▼
                       ВЕТВЛЕНИЕ ШАГА 3: ДВА ПАРАЛЛЕЛЬНЫХ ПУТИ
                                ЗАКРЫТИЯ OPEN-ROUNDTRIP
                                   │
                      ┌────────────┴────────────┐
                      ▼                         ▼
        ┌──────────────────────────┐  ┌──────────────────────────┐
        │ ШАГ 3B — close_settle    │  │ ШАГ 3C — close_sell      │
        │ (ACTIVE)                 │  │ (ACTIVE)                 │
        │ cron run_settlement.sh   │  │ host-cron 15 * * * *     │
        │ каждые 2 часа            │  │ run_close_sell.sh →      │
        │ JOIN market_resolutions  │  │ python3 -m roundtrip_    │
        │ × OPEN-roundtrips        │  │ builder --close          │
        │ UPDATE → close_type =    │  │ SELL-сделки → exact-match│
        │ SETTLEMENT_WIN/LOSS      │  │ по position_key + fuzzy- │
        │ close_price = 1.0/0.0    │  │ fallback по (wallet,     │
        │                          │  │ market, outcome) →       │
        │                          │  │ UPDATE close_type='SELL' │
        │                          │  │ + реальная цена выхода   │
        └──────────────┬───────────┘  └──────────────┬───────────┘
                       │                             │
                       └──────────────┬──────────────┘
                                      ▼
                          [Шаг 4 — update_whale_pnl]
                          update_whale_pnl_from_roundtrips()
                          Cron run_settlement.sh, Step 3 после 3B
                          ВАЖНО: шаг 4 не вызывается из 3C-cron'а —
                          между 3C (:15) и 4 (:00 чётных часов) лаг
                          до 2 часов; whales агрегаты отстают от
                          whale_trade_roundtrips (см. §13 RF#2 шага 3C)
                          Full recompute агрегатов whales из CLOSED
                          roundtrip-ов (total_pnl_usd, win/loss,
                          win_rate, avg_pnl, total_roundtrips)
                                  │
                                  ▼
            ╔══════════════════════════════════════════════════╗
            ║ МАГИСТРАЛЬ ОДНОЙ СДЕЛКИ ЗАМКНУЛАСЬ               ║
            ║                                                  ║
            ║ Данные whales → вход в governance-контур:        ║
            ║   • whale selection / copy_status promotion      ║
            ║   • paper-ветка (P1, P2, ... — sidebar)          ║
            ║   • real execution (BuilderClient, DORMANT)      ║
            ║                                                  ║
            ║ Эти фазы — не магистраль, описываются отдельно   ║
            ╚══════════════════════════════════════════════════╝
▼
┌──────────────────────────────────────────────────────────────────────┐
│ ШАГ 4 завершился: агрегаты `whales` обновлены                        │
│ (это вход в governance-контур)                                       │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼ (раз в неделю, governance-окно оператора, воскресенье)
┌──────────────────────────────────────────────────────────────────────┐
│ ШАГ 5 — governance_analytics                                         │
│ Сбор аналитики для governance-решения.                               │
│                                                                      │
│ Три параллельных источника:                                          │
│   • Weekly AI whale analysis  (cron 0 9 * * 0, автоматический)       │
│     → INSERT в whale_ai_analysis + Telegram alert с SQL-командами    │
│   • Daily Whale Alert Monitor (cron 0 8 * * *, автоматический)       │
│     → Telegram alert (read-only)                                     │
│   • whale_audit.sql + whale_status.sql (ручной, DBeaver, еженедельно)│
│     → отчёт оператору (read-only)                                    │
│                                                                      │
│ ШАГ 5 НЕ ПИШЕТ в `whales`. Запись — на шаге 6.                       │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼ (manual gate, оператор формирует план UPDATE-ов)
┌──────────────────────────────────────────────────────────────────────┐
│ ШАГ 6 — governance_decision (manual gate)                            │
│ Единственная точка изменения whales.copy_status во всей системе.     │
│                                                                      │
│ Workflow трёх акторов:                                               │
│   • Владелец проекта пересылает шаг-5 артефакты в чат аналитики      │
│   • Чат аналитики формирует план UPDATE-ов с обоснованиями           │
│   • Владелец проекта согласовывает план                              │
│   • Roo выполняет UPDATE-ы в БД                                      │
│                                                                      │
│ 5 канонических переходов (WHALE_STATUS_TRANSITIONS.md v1.1 §3):      │
│   none → tracked                                                     │
│   tracked → paper      (mandatory whale_status.sql + estimated_      │
│                         capital по одному из 4 методов)              │
│   paper → tracked      (downgrade, estimated_capital сохраняется)    │
│   any → excluded       (с обязательным exclusion_reason)             │
│   excluded → tracked/paper (recovery, при → paper пересчёт капитала) │
│                                                                      │
│ Косвенные downstream-эффекты commit UPDATE:                          │
│   • trigger_copy_whale_trade при следующих INSERT whale_trades       │
│     начнёт/прекратит создавать paper_trades                          │
│   • discovery / tracker (фильтр `copy_status != 'excluded'` в        │
│     ON CONFLICT) перестают перезаписывать excluded-китов             │
│   • polling-циклы фильтруют по новому набору paper / tracked         │
│   • materialized views — на следующем refresh (15 */2 * * *)         │
│                                                                      │
│ Никаких triggers на whales. Никаких автоматических UPDATE-ов         │
│ copy_status. БД не валидирует выполнение pre-actions.                │
└──────────────────────────────────────────────────────────────────────┘
               ▼
                CYCLE: новые whale_trades → шаги 1-4 →
                новые агрегаты `whales` → новый шаг 5/6

═══════════════════════════════════════════════════════════════════════
   PAPER-ВЕТКА (P1–P4) — синхронная и асинхронная side-route
═══════════════════════════════════════════════════════════════════════

Активируется параллельно магистрали 1–4 для китов с copy_status='paper'.
Точка входа — DB-trigger на commit шага 2B.

session.commit() шага 2B
       │
       │  для китов с copy_status = 'paper'  (синхронно, в той же транзакции)
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ P1 (сквозной 7) — trigger_copy_whale_trade                           │
│ AFTER INSERT ON whale_trades                                         │
│   • бессрочная дедупликация по tx_hash + 5-мин окно whale/market/side│
│   • Kelly: proportion = whale_size / estimated_capital;              │
│             our_size = proportion × our_bankroll × kelly_fraction    │
│             COALESCE(estimated_capital, 100000) для NULL             │
│             CAP: LEAST(our_size, bankroll × max_position_pct)        │
│   • INSERT в paper_trades                                            │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼ (по дизайну — синхронно, второй trigger в той же транзакции;
                  В ПРОДЕ НЕ РЕАЛИЗОВАНО — см. пометку ниже)
┌──────────────────────────────────────────────────────────────────────┐
│ trigger_notify_paper_trade — НЕ ПРИМЕНЁН В БД                        │
│ AFTER INSERT ON paper_trades (по дизайну в                           │
│ scripts/add_telegram_notifications.sql, не выполнен)                 │
│   • По дизайну: INSERT в paper_trade_notifications (notified=FALSE)  │
│   • Фактически: pg_trigger пуст, paper_trade_notifications не        │
│     пополняется                                                      │
│   • Возможная будущая интеграция (вероятно понадобится в prod)       │
└──────────────┬───────────────────────────────────────────────────────┘
               │ (асинхронно, отдельный процесс — также не реализовано)
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ P2 (сквозной 8) — NotificationWorker — НЕ РЕАЛИЗОВАНО В ПРОДЕ        │
│ По дизайну: src/monitoring/notification_worker.py, контейнер `bot`   │
│   • По дизайну: polling 2s SELECT WHERE notified=FALSE               │
│   • По дизайну: Telegram alert с whale_address, market, side, price  │
│   • По дизайну: UPDATE notified = TRUE                               │
│   • Фактически: paper_trade_notifications не пополняется             │
│     (см. блок выше), worker'у нечего читать                          │
│   • Уведомления о paper-сделках в проде отсутствуют                  │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼ (никаких UPDATE на paper_trades; status остаётся 'open')
┌──────────────────────────────────────────────────────────────────────┐
│ P3 (сквозной —) — нет шага settlement                                │
│ paper_trades.status остаётся 'open' постоянно. Settlement отдельным  │
│ процессом не происходит. P&L paper-портфеля считается ТОЛЬКО         │
│ через materialized views (P4).                                       │
│ Старый Python-движок paper_position_settlement.py — DEPRECATED,      │
│ disabled в main.py (см. PROJECT_STATE).                              │
└──────────────┬───────────────────────────────────────────────────────┘
               │ (асинхронно, cron 15 */2 * * *)
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ P4 (сквозной 9) — materialized views (расчёт paper P&L)              │
│ scripts/refresh_views.sh — refresh каждые 2 часа                     │
│   • paper_simulation_pnl                                             │
│       our_pnl_usd = whale_pnl × (kelly_size / whale_size)            │
│       (PHASE4-004 — стандарт формулы)                                │
│       INNER JOIN paper_trades × whale_trade_roundtrips по            │
│       (market_id, lower(wallet_address), side↔open_side)             │
│       → our_pnl только для CLOSED-roundtrip-ов;                      │
│         OPEN → our_pnl=NULL; нет матча → сделка не во view           │
│         (match rate ≈ 64.6%, см. RF1 шага 9)                        │
│   • paper_portfolio_state                                            │
│       current_balance = initial_bankroll + realized_pnl              │
│   • whale_pnl_summary                                                │
│       агрегат P&L per-whale (включая excluded)                       │
│                                                                      │
│ Это единственный источник paper P&L в системе.                       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Таблица шагов магистрали

| ID | Файл | Статус | Дата верификации | TL;DR |
|----|------|--------|------------------|-------|
| 1 | `PIPELINE_MAP_1_read_api.md` | ACTIVE | 2026-05-09 | Контейнер whale-detector запускает discovery-цикл (60s), который читает сделки из Polymarket Data API и формирует `List[TradeWithAddress]` без записи в БД. 4 других цикла (paper/tracked/HOT/WARM) — параллельный сбор данных для уже известных китов, не магистраль |
| 2A | `PIPELINE_MAP_2A_whale_registration.md` | ACTIVE | 2026-05-10 | Discovery-цикл агрегирует сделки по адресам и для трейдеров с ≥10 сделок выполняет INSERT/UPDATE в `whales` через `ON CONFLICT` с защитой `WHERE copy_status != 'excluded'` |
| 2B | `PIPELINE_MAP_2B_whale_trades_write.md` | ACTIVE | 2026-05-11 | Каждая сделка записывается через `WhaleTradesRepo.save_trade()` с валидацией, lookup `whale_id`, дедупликацией по `tx_hash`; commit активирует DB-trigger paper-ветки |
| 3A | `PIPELINE_MAP_3A_roundtrip_open.md` | ACTIVE | 2026-05-14 | Контейнер `roundtrip_builder` раз в 2 часа сканирует BUY-сделки в `whale_trades`, агрегирует их по тройке `(wallet, market, outcome)` и создаёт OPEN-roundtrip в `whale_trade_roundtrips` через `ON CONFLICT DO NOTHING` |
| 3B | `PIPELINE_MAP_3B_close_settlement.md` | ACTIVE | 2026-05-14 | cron `run_settlement.sh` каждые 2 часа JOIN-ит `market_resolutions` × OPEN-roundtrip-ы и UPDATE-ит их до `close_type='SETTLEMENT_WIN'/'SETTLEMENT_LOSS'` с `close_price=1.0/0.0` |
| 3C | `PIPELINE_MAP_3C_close_sell.md` | ACTIVE | 2026-05-28 | Параллельная ветвь шага 3, реактивирована TRD-443 (2026-05-19). Host-cron `15 * * * *` запускает `scripts/run_close_sell.sh`, который вызывает `python3 -m src.strategy.roundtrip_builder --close` напрямую на хосте (не docker, не systemd, не supervisor). Метод `run_close_positions()` читает SELL-сделки из `whale_trades`, группирует по `(wallet, market, outcome)`, ищет OPEN-roundtrip через exact-match по `position_key` (с темпоральным фильтром `traded_at > opened_at` и оконной функцией) или fuzzy-fallback по `(wallet, market, outcome)` с пониженной уверенностью — и UPDATE-ит roundtrip до `close_type='SELL'` с реальной ценой выхода. Поля: `matching_method ∈ {DIRECT_SELL, FUZZY_FLIP}`, `matching_confidence ∈ {HIGH, LOW}`, `pnl_status ∈ {EXACT, ESTIMATED}` (post-TRD-443 ternary-логика). Доля 3C в общем объёме закрытий низкая и инжест-зависимая. Не вызывает `_update_whales_pnl` — асинхронный race с шагом 4 через БД, лаг до 2 часов (см. §13 RF#2 документа 3C). Legacy: 530 FLIP pre-TRD-443 строк помечены `is_legacy_close=TRUE`, 160 sentinel `MANUAL_RUN_TRD443` строк — одноразовый backfill реактивации (см. §16) |
| 4 | `PIPELINE_MAP_4_update_whale_pnl.md` | ACTIVE | 2026-05-14 | SQL-функция `update_whale_pnl_from_roundtrips()` вызывается из той же cron-задачи `run_settlement.sh` (Step 3 после 3B) и одним UPDATE-statement пересчитывает агрегаты P&L в `whales` (total_pnl_usd, win/loss counts, win_rate, avg_pnl, total_roundtrips) на основе CLOSED-roundtrip-ов. Финальный шаг первого потока — далее данные становятся входом в governance-контур |
| 5 | `PIPELINE_MAP_5_governance_analytics.md` | MANUAL-ACTIVE / cron | 2026-05-25 | Первый шаг governance-контура. Раз в неделю владелец проекта открывает governance-окно: получает Telegram-сводку Weekly AI (cron `0 9 * * 0`, OpenRouter, запись в `whale_ai_analysis`), просматривает Daily Whale Alert Monitor (cron `0 8 * * *`), запускает в DBeaver `whale_audit.sql` (обзорный) и `whale_status.sql` (deep dive по кандидатам). Шаг ничего не пишет в `whales` |
| 6 | `PIPELINE_MAP_6_governance_decision.md` | MANUAL-ACTIVE | 2026-05-27 | Единственная write-точка в `whales.copy_status`. Workflow трёх акторов: владелец проекта пересылает результаты шага 5 в чат аналитики → чат аналитики формирует список переходов с обоснованием → владелец проекта согласовывает → Roo выполняет UPDATE-ы по правилам `WHALE_STATUS_TRANSITIONS.md v1.1` §3 (5 канонических переходов: `none↔tracked↔paper`, `any→excluded`, recovery). Никаких triggers / автоматических процессов на `whales` |

---

## 3. Sidebar-документы (вне магистральной нумерации)

| ID | Файл | Статус | Когда использовать |
|----|------|--------|---------------------|
| 1B | `PIPELINE_MAP_1B_market_metadata_cache.md` | ACTIVE | Lookup-сервис обогащения `market_title` / `market_category`. Вызывается из активных модулей, но не state-изменение сделки. Ссылаться при обсуждении HOT/WARM-циклов или `market_category` |
| 1C | `PIPELINE_MAP_1C_builder_client.md` | INACTIVE / DORMANT | Real-execution через `BuilderClient`. Полностью dormant в Phase 2B. Использовать как pre-flight checklist при будущем включении real execution |

### Paper-ветка (P1–P4)

Параллельная side-route магистрали для китов с `copy_status='paper'`. Активируется DB-trigger'ом `trigger_copy_whale_trade` на commit шага 2B (синхронно, в той же транзакции). Не модифицирует основные сделки кита в `whale_trades` — рождает новую сущность `paper_trades`. Жизненный цикл paper-сделки не дублирует жизненный цикл сделки кита: paper-сделка **никогда не закрывается** UPDATE-ом, её P&L материализуется косвенно через JOIN с CLOSED-roundtrip-ами кита в materialized views.

Поток paper-ветки в бизнес-нотации:
SHA-1 BUY-сделки кита-paper попадает в whale_trades (шаг 2B)
│
├── P1 / сквозной 7 (синхронно):
│     DB-trigger пересчитывает Kelly sizing
│     с дедупликацией tx_hash и 5-минутного окна
│     → одна строка в paper_trades
│
├── (по дизайну — синхронно, второй trigger):
│     trigger_notify_paper_trade → paper_trade_notifications
│     ФАКТИЧЕСКИ: trigger не применён в БД,
│     paper_trade_notifications не пополняется.
│     Уведомления о paper-сделках в проде отсутствуют.
│
├── P2 / сквозной 8 (по дизайну — асинхронно, polling 2s):
│     NotificationWorker → Telegram alert
│     ФАКТИЧЕСКИ: не реализовано в production
│     (нет источника данных в paper_trade_notifications).
│     Вероятно понадобится в проде — отдельная задача.
│
├── P3 / сквозной — (отсутствует как процесс):
│     paper_trades.status остаётся 'open' навсегда.
│     Settlement через UPDATE paper_trades не выполняется
│     ни одним production-процессом.
│
└── P4 / сквозной 9 (асинхронно, cron каждые 2 часа :15):
REFRESH MATERIALIZED VIEW (whale_pnl_summary,
paper_portfolio_state, paper_simulation_pnl)
→ P&L paper-портфеля материализуется через JOIN
paper_trades × CLOSED whale_trade_roundtrips
(формула: our_pnl = whale_pnl × kelly_size / whale_size,
стандарт PHASE4-004)

**Таблица шагов paper-ветки** (формат аналогичен магистральной таблице §2):

| ID | Файл | Статус | Дата верификации | TL;DR |
|----|------|--------|------------------|-------|
| 7 (P1) | `PIPELINE_MAP_7_paper_trigger.md` | ACTIVE | 2026-05-27 | DB-trigger `trigger_copy_whale_trade` AFTER INSERT ON `whale_trades` создаёт строку в `paper_trades` для китов с `copy_status='paper'`. Считает Kelly: `our_size = (whale_size / COALESCE(estimated_capital, 100000)) × our_bankroll × kelly_fraction`, CAP через `max_position_pct`. Бессрочная дедупликация по `tx_hash` + 5-минутное окно по `(whale, market, side)`. Запись `paper_trades.status='open'` устанавливается при INSERT и **не изменяется** на протяжении всего жизненного цикла. По дизайну ожидался второй trigger `trigger_notify_paper_trade` для уведомлений — **в БД не применён**, paper_trade_notifications не пополняется |
| 8 (P2) | `PIPELINE_MAP_8_notification_worker.md` | TODO (не реализовано в production) | 2026-05-27 | По дизайну: `NotificationWorker` в контейнере `bot` опрашивает `paper_trade_notifications WHERE notified=FALSE` и отправляет Telegram alert. **Фактически:** ни trigger `trigger_notify_paper_trade`, ни worker не активны в production — paper_trade_notifications не пополняется. Уведомления о paper-сделках в проде отсутствуют. Вероятно понадобится в проде — отдельная задача активации |
| — (P3) | (нет файла) | NOT-PRESENT | 2026-05-26 | Settlement paper-сделок как отдельный процесс **не существует**. `paper_trades.status` остаётся `'open'` навсегда. Старый Python-движок `src/strategy/paper_position_settlement.py` — DEPRECATED (PROJECT_STATE: `disabled in main.py, replaced by roundtrip_builder`), писал в `trades` table (не в `paper_trades`). Любая логика «закрытия» paper-позиции выполняется неявно через JOIN на шаге 9 (P4) |
| 9 (P4) | `PIPELINE_MAP_9_paper_pnl_views.md` | ACTIVE | 2026-05-28 | Host-cron `scripts/refresh_views.sh` каждые 2 часа в :15 (`15 */2 * * *`) выполняет `REFRESH MATERIALIZED VIEW CONCURRENTLY` для трёх view: `whale_pnl_summary` (агрегат P&L per-whale, `copy_status IN paper/tracked/excluded`), `paper_portfolio_state` (одна строка: `current_balance = initial_bankroll + realized_pnl`, `initial_bankroll` из `strategy_config.our_bankroll`), `paper_simulation_pnl` (per-trade P&L через INNER JOIN `paper_trades × whale_trade_roundtrips` по `(market_id, lower(wallet_address), side↔open_side)`, формула PHASE4-004 `our_pnl = whale_pnl × our_size / whale_size` только для CLOSED). Оба paper-view считают P&L от `bankroll_reset_at` (fallback 2026-04-04), не за всю историю. **Единственный** источник paper P&L. Финальный шаг paper-ветки. RED FLAG: INNER JOIN + требование сопоставленного roundtrip → ~35% paper-сделок не попадают в P&L (match rate ≈ 64.6%) |

**Связь с магистральной нумерацией:**

- **Вход в paper-ветку**: shared commit с шагом 2B магистрали. P1 — синхронный downstream-эффект коммита 2B, не отдельная асинхронная задача.
- **Косвенный вход через шаг 6**: оператор через UPDATE `whales.copy_status='paper'` включает кита в paper-ветку; следующая BUY-сделка этого кита активирует P1. До UPDATE сделки записываются в `whale_trades` без активации paper-ветки.
- **Косвенный выход в governance**: P4 (`whale_pnl_summary`, `paper_simulation_pnl`) читаются на шаге 5 (Manual SQL §300, §500) как обоснование решений шага 6. Это и есть «цикл» governance-контура (см. ASCII-схему §1).

**Связь с шагом 1C (sidebar — DORMANT real execution):**

P-ветка описывает **только paper-симуляцию**. Реальное исполнение через `BuilderClient` (sidebar 1C, DORMANT) — отдельная ветка, потенциально активируемая в будущем. При гипотетической активации live-execution параллельно paper-ветке потребуется отдельная нумерация (например, L1–L4) и отдельные документы. Текущий INDEX это не описывает.

**Sidebar для paper-ветки**:

| ID | Файл | Статус | Когда использовать |
|----|------|--------|---------------------|
| (Grafana) | (нет файла, упоминание) | визуализация существует | Существует Grafana-дашборд с визуализацией paper P&L и состояния портфеля. Не описывается отдельным документом; источник данных — те же materialized views шага 9 (P4) |
| (paper_position_settlement) | (нет файла, упоминание) | DEPRECATED | `src/strategy/paper_position_settlement.py` — старый Python-движок, отключён в `main.py` (PROJECT_STATE: PIPE-041, 2026-04-18). Не входит в активный pipeline. Кандидат на удаление отдельной hygiene-задачей. Упомянут в RF шага P3 (`paper_trades.status` не закрывается) для предотвращения путаницы будущих читателей |