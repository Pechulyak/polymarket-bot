# PIPELINE_MAP_INDEX

**Статус документа:** обязательное первое чтение для любого чата, работающего над pipeline_map
**Последнее обновление:** 2026-05-15 (добавлено описание шага 3C в формате α — DORMANT-ветка с pre-flight checklist; магистраль покрыта 7/7 шагов)
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
        │ (ACTIVE)                 │  │ (DORMANT в auto-pipeline)│
        │ cron run_settlement.sh   │  │ _close_roundtrips()      │
        │ каждые 2 часа            │  │ существует в коде, в     │
        │ JOIN market_resolutions  │  │ production не вызывается │
        │ × OPEN-roundtrips        │  │ ни одним cron/docker/    │
        │ UPDATE → close_type =    │  │ supervisor               │
        │ SETTLEMENT_WIN/LOSS      │  │ (флаг --close не         │
        │ close_price = 1.0/0.0    │  │ используется)            │
        └──────────────┬───────────┘  └──────────────┬───────────┘
                       │                             │
                       └──────────────┬──────────────┘
                                      ▼
                          [Шаг 4 — update_whale_pnl]
                          update_whale_pnl_from_roundtrips()
                          Cron run_settlement.sh, Step 3 после 3B
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
| 3C | `PIPELINE_MAP_3C_close_sell.md` | DORMANT (описан) | 2026-05-15 | Параллельная DORMANT-ветвь шага 3: альтернативный механизм закрытия OPEN-roundtrip-ов через прямое сопоставление с SELL-событиями кита. В production не запускается ни одним runner-ом (CLI-флаг `--close` не передаётся ни docker-compose, ни cron, ни supervisor, ни systemd). При гипотетической ре-активации агрегировал бы SELL по `(wallet, market, outcome)`, искал OPEN-roundtrip через exact match или fuzzy fallback и UPDATE-ил его до `close_type='SELL'`. Конкурирует со SQL-функцией шага 4 за те же 7 колонок `whales` (см. §13 и §16 документа 3C) |
| 4 | `PIPELINE_MAP_4_update_whale_pnl.md` | ACTIVE | 2026-05-14 | SQL-функция `update_whale_pnl_from_roundtrips()` вызывается из той же cron-задачи `run_settlement.sh` (Step 3 после 3B) и одним UPDATE-statement пересчитывает агрегаты P&L в `whales` (total_pnl_usd, win/loss counts, win_rate, avg_pnl, total_roundtrips) на основе CLOSED-roundtrip-ов. Финальный шаг магистрали — далее данные становятся входом в governance-контур (вне магистрали) |

---

## 3. Sidebar-документы (вне магистральной нумерации)

| ID | Файл | Статус | Когда использовать |
|----|------|--------|---------------------|
| 1B | `PIPELINE_MAP_1B_market_metadata_cache.md` | ACTIVE | Lookup-сервис обогащения `market_title` / `market_category`. Вызывается из активных модулей, но не state-изменение сделки. Ссылаться при обсуждении HOT/WARM-циклов или `market_category` |
| 1C | `PIPELINE_MAP_1C_builder_client.md` | INACTIVE / DORMANT | Real-execution через `BuilderClient`. Полностью dormant в Phase 2B. Использовать как pre-flight checklist при будущем включении real execution |

### Paper-ветка (P1, P2, ...)

Не описана. Активируется DB-trigger'ом `trigger_copy_whale_trade` на INSERT в `whale_trades` (срабатывает синхронно в commit шага 2B), но только для китов с `copy_status='paper'`. Включает таблицы `paper_trades`, `paper_trade_notifications`, settlement через cron `run_settlement.sh`, materialized views `paper_simulation_pnl`, `paper_portfolio_state`. Описывать после стабилизации магистрали 1 → 2A → 2B → 3A/3B/3C → 4.