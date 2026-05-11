# PIPELINE_MAP_INDEX

**Статус документа:** обязательное первое чтение для любого чата, работающего над pipeline_map
**Последнее обновление:** 2026-05-11
**Источник истины о магистрали сделки:** этот файл + связанные `PIPELINE_MAP_*.md`

---

## 0. Что такое pipeline_map

Pipeline_map — это карта **магистрального пути одной сделки** кита от момента её обнаружения через внешний Polymarket Data API до достижения сделкой финального состояния в системе. Документ описывает state-изменения сделки и точки ветвления магистрали; не описывает каждый компонент кода.

**Не путать с:**
- Картой зависимостей кода (для этого — `AGENTS.md`, README)
- PROJECT_STATE (только текущее состояние системы, без логики потока)
- Аудитом производительности или безопасности (это отдельные задачи)

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
│ Контейнер whale-detector, 5 циклов polling                           │
│ Получение List[TradeWithAddress], read-only                          │
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
│ whale_      │   │ Все 5 циклов whale-detector                     │
│ registration│   │ WhaleTradesRepo.save_trade()                     │
│ Только      │   │ INSERT в whale_trades                            │
│ discovery   │   │ Дедупликация по tx_hash (только если передан)   │
│ INSERT ON   │   │ whale_id = NULL для нерегистрированных          │
│ CONFLICT в  │   │                                                 │
│ whales      │   │ session.commit() ──┐                            │
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
            │ ШАГ 3 — roundtrip_reconstruction (ГИПОТЕЗА)     │
            │ Контейнер roundtrip_builder, while-loop 2h       │
            │ Реконструкция позиций: buy + sell → roundtrip    │
            │ INSERT в whale_trade_roundtrips                  │
            │ Источник аналитики для governance copy_status    │
            └──────────────────────┬───────────────────────────┘
                                   │
                                   ▼
                           [Шаг 4 — TBD]
                           settlement через cron run_settlement.sh
                           (вероятно, side-route, не магистраль)
```

---

## 2. Таблица шагов

### 2.1 Магистраль (описанные шаги)

| ID | Файл | Статус | Последняя верификация | TL;DR (1 предложение) |
|----|------|--------|------------------------|------------------------|
| 1 | `PIPELINE_MAP_1_read_api.md` | ACTIVE | 2026-05-09 | Контейнер whale-detector в 5 циклах читает сделки из Polymarket Data API и формирует `List[TradeWithAddress]` без записи в БД |
| 2A | `PIPELINE_MAP_2A_whale_registration.md` | ACTIVE | 2026-05-10 | Discovery-цикл агрегирует сделки по адресам, и для трейдеров с ≥10 сделок INSERT/UPDATE в `whales` через `ON CONFLICT` с защитой `WHERE copy_status != 'excluded'` |
| 2B | `PIPELINE_MAP_2B_whale_trades_write.md` | ACTIVE | 2026-05-11 | Все 5 циклов записывают каждую сделку через `WhaleTradesRepo.save_trade()` с валидацией, lookup `whale_id`, дедупликацией по `tx_hash`; commit активирует DB-trigger paper-ветки |
| 3 | `PIPELINE_MAP_3_roundtrip_reconstruction.md` | TBD | — | **ГИПОТЕЗА**: `roundtrip_builder` раз в 2 часа реконструирует позиции из `whale_trades` в `whale_trade_roundtrips`; источник аналитики для смены `copy_status` |

### 2.2 Sidebar-документы (вне магистральной нумерации)

| ID | Файл | Статус | Когда использовать |
|----|------|--------|---------------------|
| 1B | `PIPELINE_MAP_1B_market_metadata_cache.md` | ACTIVE | Lookup-сервис обогащения `market_title` / `market_category`. Вызывается из активных модулей, но не state-изменение сделки. Ссылаться при обсуждении HOT/WARM-циклов или `market_category` |
| 1C | `PIPELINE_MAP_1C_builder_client.md` | INACTIVE / DORMANT | Real-execution через `BuilderClient`. Полностью dormant в Phase 2B. Использовать как pre-flight checklist при будущем включении real execution |

### 2.3 Paper-ветка (sidebar магистрали, отдельная нумерация P)

Не описана. Активируется DB-trigger'ом `trigger_copy_whale_trade` на INSERT в `whale_trades` (срабатывает синхронно в commit шага 2B), но только для китов с `copy_status='paper'`. Включает:
- `paper_trades` — целевая таблица trigger'а
- `paper_trade_notifications` — очередь уведомлений (Telegram)
- Settlement через cron `run_settlement.sh`
- Materialized views `paper_simulation_pnl`, `paper_portfolio_state`

Описывать после стабилизации магистрали 1 → 2A → 2B → 3 → 4.

---

## 3. Статусы компонентов (REACHABLE / DORMANT / SCRIPT-ONLY)

### REACHABLE — выполняются в активном production

| Компонент | Контейнер / Точка входа | Используется в шагах |
|-----------|--------------------------|----------------------|
| `PolymarketDataClient` | `whale-detector` / `run_whale_detection.py` | 1 |
| `WhaleDetector` (5 циклов) | `whale-detector` | 1, 2A, 2B |
| `WhalePoller` (HOT/WARM) | `whale-detector` (через `RealTimeWhaleMonitor`) | 1, 2B |
| `WhaleTradesRepo.save_trade()` | `whale-detector` | 2B |
| `_save_whale_to_db()` | `whale-detector` | 2A |
| DB-trigger `trigger_copy_whale_trade` | postgres, on `whale_trades AFTER INSERT` | 2B → paper-ветка |
| `roundtrip_builder` | контейнер `roundtrip_builder`, while-loop 2h | 3 (гипотеза) |
| `market_title_cache` / `market_category_cache` | `whale-detector`, `bot` | 1B (sidebar), используется в 2B для HOT/WARM |

### DORMANT — код существует, но не достижим в текущей топологии

| Компонент | Причина DORMANT |
|-----------|------------------|
| `WhaleTracker` | Не импортируется в `run_whale_detection.py`; верифицировано (PIPELINE-MAP-STEP-2-DISCOVERY раздел 6) |
| `VirtualBankroll` | Закомментирован в `main.py`; PROJECT_STATE: FROZEN |
| `CopyTradingEngine` | Импортируется только из `main_paper_trading.py`, который не запущен; PROJECT_STATE: FROZEN |
| `BuilderClient` и связанная инфраструктура | Полная цепочка dormant; см. `PIPELINE_MAP_1C_builder_client.md` |
| `PaperPositionSettlementEngine` | DEPRECATED, заменён cron-скриптом `run_settlement.sh` |
| Callback `on_whale_detected` | Определён в `WhaleDetector`, но не передаётся в `run_whale_detection.py:189–194`; SCRIPT-ONLY |

### SCRIPT-ONLY — запуск через cron или вручную, не docker-compose

| Скрипт | Расписание | Назначение |
|--------|------------|------------|
| `category_backfill.py` | cron каждые 2 часа | Дозаполнение `market_category` = `'unknown'` в `whale_trades` и `whale_trade_roundtrips` |
| `pipeline_monitor` | cron каждые 30 минут | Telegram-алерты по состоянию pipeline |
| `Daily Whale Alert Monitor` | cron 08:00 UTC | Daily Telegram alerts |
| `run_settlement.sh` | cron (вероятно 2h) | Закрытие позиций по resolved markets |
| `Weekly AI whale analysis` | cron weekly | AI-анализ китов через LLM |
| `update_whale_activity_counters` | hourly из самого `whale-detector` | Пересчёт `trades_last_3_days/7_days`, `days_active_*` в `whales` из реальных данных `whale_trades` (перекрывает эвристики шага 2A) |

---


## 4. Правила работы с pipeline_map (для нового чата)

### Обязательные первые действия

1. **Прочитать этот INDEX целиком**
2. **Прочитать `PROJECT_STATE.md`** — актуальное состояние системы
3. **Прочитать `PROJECT_STATE_GOVERNANCE.md`** — правила ведения PROJECT_STATE
4. **Прочитать те шаги, которые касаются текущей задачи** — не загружать все шаги в context window заранее
5. Сформулировать гипотезу следующего шага и запросить подтверждение Master перед TASK PACK'ом

### Метод определения следующего шага

См. context transfer документ (`DOC-PIPELINE-MAP` раздел 2). Главный принцип: следующий шаг определяется **по физическому потоку state-изменений сделки**, не по структуре кода и не по бизнес-нумерации.

### Правила формата (эталон — шаг 1)

См. context transfer раздел 7 «Формат шага карты». Структура TL;DR + §§1–15. Самопроверка двухпроходная (формат + факты). Каждое утверждение в основном тексте — с цитатой `файл:строка` или ссылкой на конкретный отчёт Roo. Интерпретации — только в §13.

### Правила обновления INDEX

При каждой правке любого шага или добавлении нового:
1. Обновить §2 «Таблица шагов» (статус, дата верификации, TL;DR если изменилось)
2. Обновить §4 «RED FLAG'и» при добавлении новых или закрытии существующих
3. Добавить запись в §5 «История правок»
4. Если меняется структура магистрали — обновить ASCII-схему в §1

Не обновлённый INDEX = устаревший. Это часть «Прохода A» самопроверки шага.

---

## 5. Что использовать как первое чтение для нового чата

**Минимальный набор для понимания контекста:**
1. `PIPELINE_MAP_INDEX.md` (этот файл)
2. `PROJECT_STATE.md`
3. Context transfer документ (`DOC-PIPELINE-MAP`)

**Для работы над конкретным шагом N:** дополнительно загрузить шаг N-1, шаг N (если существует и нужна доработка), и шаг N+1 (если есть гипотеза).

**Не загружать заранее:** все остальные шаги, sidebar-документы (1B, 1C), `AGENTS.md`, схемы БД — это можно подгрузить через `project_knowledge_search` по запросу.