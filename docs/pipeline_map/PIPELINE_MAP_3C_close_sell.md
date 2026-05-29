# ШАГ 3C. ЗАКРЫТИЕ OPEN-ROUNDTRIP ЧЕРЕЗ SELL-СОБЫТИЯ КИТА

## Краткая характеристика (TL;DR)

Шаг 3 магистрали разделён на три параллельные ветви по типу действия над `whale_trade_roundtrips`:

- **Шаг 3A** — создание новых OPEN-позиций из BUY-сделок (описан отдельно).
- **Шаг 3B** — закрытие OPEN-позиций через резолюцию рынка (описан отдельно).
- **Шаг 3C** — закрытие OPEN-позиций через SELL-события кита (этот документ).

### Шаг 3C в бизнес-нотации

Каждый час в `:15` host-cron запускает `scripts/run_close_sell.sh`, который активирует Python-точку входа `python3 -m src.strategy.roundtrip_builder --close`. Скрипт читает `whale_trades` с `side='sell'`, агрегирует SELL-события по тройке `(wallet_address, market_id, outcome)` в группы, и для каждой группы ищет соответствующий OPEN-roundtrip в `whale_trade_roundtrips`. Найденный OPEN UPDATE-ится до `status='CLOSED'` с `close_type='SELL'` и расчётом P&L по реальной цене SELL-сделки. Поиск идёт в два прохода: сначала **exact-match** по `position_key` (та же тройка ключей), при неудаче — **fuzzy-fallback** по `(wallet, market, outcome)` с пониженной уверенностью.

Шаг описывает только UPDATE OPEN → CLOSED через Python-метод `_close_roundtrips()`. Пересчёт P&L кита (`update_whale_pnl_from_roundtrips`) — отдельный шаг 4, вызывается из независимого cron `run_settlement.sh`; связь между 3C и 4 — асинхронная через БД (см. §14).

**Доля 3C в общей топологии закрытий низкая и инжест-зависимая.** Подавляющее большинство OPEN-roundtrip-ов закрывается шагом 3B (settlement по резолюции рынка). 3C обрабатывает только те позиции, по которым кит фактически продал свою долю до резолюции рынка и эта SELL-сделка попала в `whale_trades` через шаг 2B.

---

## 1. Назначение шага

Шаг переводит OPEN-позицию в `whale_trade_roundtrips` в финальное состояние CLOSED **по реальной цене выхода кита**, когда кит продаёт позицию до резолюции рынка. Это второй из двух auto-trigger механизмов закрытия позиций; альтернативный — шаг 3B по бинарной цене резолюции (1.0/0.0).

Бизнес-смысл: «кит вышел из позиции по рынку → знаем реальную цену продажи → проставляем по этой позиции, сколько кит реально заработал/потерял, не дожидаясь резолюции рынка».

Без шага 3C позиции, по которым кит вышел через SELL до резолюции, либо остались бы OPEN до самой резолюции (тогда закрылись бы по бинарной 1.0/0.0, что искажает P&L), либо потребовали бы ручного закрытия. 3C даёт точную цену выхода и корректное `pnl_status='EXACT'` для таких позиций.

---

## 2. Статус

**CONFIRMED-ACTIVE.** Host-cron `15 * * * *` (user crontab) запускает `scripts/run_close_sell.sh`. Скрипт активирует Python-точку входа `python3 -m src.strategy.roundtrip_builder --close` напрямую на хосте (не через `docker exec`, не через docker-сервис). Pipeline реактивирован 2026-05-19 в рамках TRD-443; ранее имел статус DORMANT.

Дата верификации: 2026-05-28.

---

## 3. Исходные файлы

**Триггер и оркестрация:**
- `/root/polymarket-bot/scripts/run_close_sell.sh` — bash-скрипт: подгрузка `.env`, переход в workdir, вызов `python3 -m src.strategy.roundtrip_builder --close`.
- `crontab` (user) — строка `15 * * * * /root/polymarket-bot/scripts/run_close_sell.sh >> /root/polymarket-bot/logs/close_sell_cron.log 2>&1`.

**Python-точка входа:**
- `src/strategy/roundtrip_builder.py` — основной модуль. CLI-обработка флага `--close` маршрутизирует выполнение в метод `run_close_positions()`.

**Ключевые методы (актуальная post-TRD-443 версия):**
- `run_close_positions()` — главный entry для close-pipeline, два шага: `_fetch_and_group_sell_trades()` → `_close_roundtrips()`. Не вызывает `_update_whales_pnl` (см. §14 и RED FLAG #2).
- `_fetch_and_group_sell_trades()` — читает SELL-сделки из `whale_trades`, группирует по `(wallet_address, market_id, outcome)`.
- `_close_roundtrips()` — основной матчинг-движок. Содержит два SQL-CTE: `ranked_query` (exact-match) и `fuzzy_query` (fuzzy-fallback).

**SQL-CTE внутри `_close_roundtrips()`:**
- `ranked_query` (lines 368–400) — exact-match по `position_key`, с темпоральным фильтром `wt.traded_at > rt.opened_at` (line 390) и оконной функцией `ROW_NUMBER() OVER (ORDER BY wt.traded_at DESC, wt.id DESC)` (lines 380–383).
- `fuzzy_query` (lines 408–443) — fuzzy-fallback по `(wallet, market, outcome)` без position_key, с фильтрами `wt.outcome = rt.outcome` (line 427) и `wt.traded_at > rt.opened_at` (line 430), сортировка `ORDER BY sell_traded_at DESC LIMIT 1` (lines 441–442).

**DDL целевой таблицы:**
- `scripts/migration_whale_trade_roundtrips.sql` — DDL `whale_trade_roundtrips` (описан в шаге 3A).

**Применённые миграции для расширения whitelist'ов:**
- `phase3_006` — добавление колонки `is_legacy_close BOOLEAN` + marker для 530 pre-TRD-443 строк.
- `phase3_007` — расширение CHECK-ограничения `matching_method`: добавлены `FUZZY_FLIP`, `MANUAL_RUN_TRD443`.
- `phase3_007a` — расширение CHECK-ограничения `pnl_status`: добавлены `EXACT`, `LEGACY_INVALID`.

---

## 4. Контейнер

Шаг не имеет собственного docker-контейнера. Host-cron запускает bash-скрипт на хосте, который запускает Python-процесс **напрямую через системный `python3`** (workdir `/root/polymarket-bot`). Соединение с БД устанавливается приложением через `DATABASE_URL` из `.env` (порт `polymarket_postgres` проброшен на хост).

Docker-сервис `roundtrip_builder` (контейнер `polymarket_roundtrip_builder`) существует в системе, но **не является runner-ом для 3C** — он выполняет шаг 3A (BUY-build, sleep 7200). Шаг 3C использует тот же исходный модуль `roundtrip_builder.py`, но с другим CLI-флагом (`--close`) и другим runner-ом (host-cron, не docker-loop).

Workdir скрипта: `/root/polymarket-bot` (`run_close_sell.sh`). Долгоживущего процесса нет: каждый час создаётся новый shell-процесс, который завершается после выполнения Python-вызова.

Альтернативные механизмы развёртывания (проверены, не используются): supervisor — отсутствует; systemd — `systemctl list-units` пуст для polymarket/close; docker-compose service `roundtrip_builder_close_sell` — отсутствует.

---

## 5. Триггер запуска и расписание

| Параметр | Значение | Источник |
|----------|----------|----------|
| Тип триггера | host-cron (user crontab) | `crontab -l` |
| Cron expression | `15 * * * *` | user crontab |
| Период | 1 час (каждый час UTC, минута 15) | вычислено |
| Команда | `/root/polymarket-bot/scripts/run_close_sell.sh >> /root/polymarket-bot/logs/close_sell_cron.log 2>&1` | user crontab |
| Альтернативные механизмы | systemd: не найден; supervisor: не найден; docker-compose service: отсутствует | DIAG-RF-CLARIFY 2026-05-28 |

Расписание **не координируется** с cron-задачей шага 3B/4 (`run_settlement.sh`, `0 */2 * * *`). Два независимых cron-процесса с разными периодами и разными минутами:
- 3C: ежечасно в `:15`.
- 3B+4: каждые 2 часа в `:00` чётных часов.

Раз в 2 часа окно их одновременной работы пересекается (3B+4 на `:00`, 3C на `:15` того же часа). Координация отсутствует — race-условие на `whale_trade_roundtrips` (см. RED FLAG #2, шаг 3C может писать close-данные в roundtrip, который шаг 4 уже использовал для агрегации `whales`).

---

## 6. Алгоритм шага

### 6.1 Bash-оркестратор `run_close_sell.sh`

Последовательность:

1. **Загрузка окружения**: `set -e` → `source /root/polymarket-bot/.env` через `set -a / set +a` — все переменные `.env` экспортируются в окружение.
2. **Переход в workdir**: `cd /root/polymarket-bot`.
3. **Запуск Python-точки входа**: `python3 -m src.strategy.roundtrip_builder --close >> "$LOG_FILE" 2>&1`.
4. **Завершение**: естественный exit Python-процесса.

Никаких отдельных SQL-вызовов через `docker exec` (в отличие от 3B), никакой проверки `$?` после Python-вызова — `set -e` гарантирует остановку на ненулевом exit, но явной проверки нет.

### 6.2 Python-точка входа `run_close_positions()`

CLI-флаг `--close` маршрутизирует выполнение в метод `run_close_positions()` (lines 853–899), который выполняет **два шага последовательно**:

1. `sell_groups = self._fetch_and_group_sell_trades()` — чтение SELL-сделок из `whale_trades` и агрегация по тройке `(wallet_address, market_id, outcome)`.
2. `self._close_roundtrips(sell_groups)` — основной матчинг-движок (см. §6.3).

**Что НЕ делает `run_close_positions()`:** не вызывает `_update_whales_pnl()`. Пересчёт `whales` агрегатов — ответственность шага 4 (`update_whale_pnl_from_roundtrips`), который запускается из другого cron-расписания. См. §14 и RED FLAG #2.

### 6.3 Матчинг-движок `_close_roundtrips()` — главное действие шага

Для каждой группы SELL-сделок выполняется матчинг в два прохода:

**Проход 1 — Exact-match (`ranked_query`, lines 368–400):**
- JOIN `whale_trade_roundtrips rt` × `whale_trades wt` по `rt.position_key = (wt.wallet_address, wt.market_id, wt.outcome)`.
- Фильтры: `rt.status = 'OPEN'`, `wt.side = 'sell'`, `wt.traded_at > rt.opened_at`.
- Сортировка кандидатов: `ROW_NUMBER() OVER (PARTITION BY rt.id ORDER BY wt.traded_at DESC, wt.id DESC)`. Берётся самая поздняя по времени SELL (ранг 1).
- Если совпадение найдено: `matched_via_fuzzy = False`.

**Проход 2 — Fuzzy-fallback (`fuzzy_query`, lines 408–443), активируется при неудаче exact:**
- JOIN `whale_trade_roundtrips rt` × `whale_trades wt` без `position_key`, только по `wallet_address`, `market_id`, `outcome`.
- Фильтры: `rt.status = 'OPEN'`, `wt.side = 'sell'`, `wt.outcome = rt.outcome`, `wt.traded_at > rt.opened_at`.
- Сортировка: `ORDER BY sell_traded_at DESC LIMIT 1` — берётся OPEN, для которого нашлась самая поздняя SELL.
- Если совпадение найдено: `matched_via_fuzzy = True`.

**Расчёт полей при UPDATE (lines 484–486):**
```
matching_method     = sentinel_method if sentinel_method else ('FUZZY_FLIP' if matched_via_fuzzy else 'DIRECT_SELL')
matching_confidence = 'LOW' if matched_via_fuzzy else 'HIGH'
pnl_status          = 'ESTIMATED' if matched_via_fuzzy else 'EXACT'
```

**Sentinel-механизм:** параметр `sentinel_method` позволяет переопределить `matching_method` для backfill-прогонов (используется только для ручных запусков; 160 строк с `MANUAL_RUN_TRD443` в БД — историческое наследие TRD-443 backfill).

**Прочие поля при UPDATE:**
- `status = 'CLOSED'`
- `close_type = 'SELL'`
- `close_price` = реальная цена SELL-сделки из `whale_trades.price`
- `close_size_usd` = из `whale_trades`
- `close_trade_id` = `wt.id` (FK на SELL-сделку в `whale_trades`)
- `close_side = 'sell'`
- `closed_at` = `wt.traded_at` (момент SELL-сделки на блокчейне, не `NOW()`).
- `gross_pnl_usd = net_pnl_usd = (close_price - open_price) * open_size_usd`. Поле `fees_usd` в формулу не входит и остаётся `0` (см. RED FLAG #1).

**Логирование решений матчинга:** для каждого решения внутри метода пишутся уровни `INFO` (`close_match_direct`, `close_match_skipped`) и `WARNING` (`close_match_fuzzy`). См. §12.

---

## 7. Формат выходных данных

UPDATE-ы в таблице `whale_trade_roundtrips`: OPEN → CLOSED с close_type='SELL'. Метод возвращает в caller dict со счётчиками `processed`, `closed`, `direct`, `fuzzy`, `skipped` — используется только для финального лога итерации (`SELL groups processed: N / Roundtrips CLOSED: M (direct=X, fuzzy=Y)`), наружу не экспортируется.

---

## 8. Записи в БД

### 8.1 Целевая таблица

`whale_trade_roundtrips`. DDL — `scripts/migration_whale_trade_roundtrips.sql:6–86` (описан подробно в шаге 3A).

Релевантные для шага 3C поля при UPDATE:
- `status` — `'OPEN'` → `'CLOSED'`.
- `close_type` — `'SELL'`.
- `close_price`, `close_size_usd`, `close_trade_id`, `close_side`, `closed_at` — реальные значения из SELL-сделки.
- `matching_method` — `'DIRECT_SELL'` / `'FUZZY_FLIP'` / `'MANUAL_RUN_TRD443'` (sentinel-backfill).
- `matching_confidence` — `'HIGH'` / `'LOW'`.
- `pnl_status` — `'EXACT'` / `'ESTIMATED'`.
- `gross_pnl_usd`, `net_pnl_usd` — рассчитанный P&L (равны, см. RED FLAG #1).
- `is_legacy_close` — `FALSE` для всех новых строк 3C (TRUE проставлен 530 pre-TRD-443 legacy-строкам миграцией phase3_006).
- `updated_at` — `NOW()` на момент UPDATE.

### 8.2 Операция шага: UPDATE на найденных OPEN-roundtrip-ах

Шаг 3C выполняет только UPDATE. INSERT — НЕ выполняет (это создание, шаг 3A). DELETE — НЕ выполняет.

WHERE-клауза UPDATE: `WHERE id = :roundtrip_id`. Защита от race-условий (например, если 3B уже закрыл roundtrip раньше) на уровне WHERE отсутствует — повторная проверка `status='OPEN'` не делается. Однако exact/fuzzy-запросы фильтруют по `rt.status = 'OPEN'` в SELECT-фазе; race-окно — секунды между SELECT и UPDATE одного roundtrip. См. RED FLAG #3.

### 8.3 CHECK-ограничения целевой таблицы (post-TRD-443)

После применения phase3_007 / 007a в production действуют расширенные whitelist'ы:
- `matching_method ∈ {DIRECT_SELL, SETTLEMENT, FLIP, PARTIAL, MANUAL_REVIEW, FUZZY_FLIP, MANUAL_RUN_TRD443}`.
- `pnl_status ∈ {CONFIRMED, ESTIMATED, UNAVAILABLE, EXACT, LEGACY_INVALID}`.

Значения, которые пишет шаг 3C (`DIRECT_SELL`, `FUZZY_FLIP`, `EXACT`, `ESTIMATED`), все входят в whitelist.

---

## 9. Условия успеха / частичного успеха / неуспеха

| Исход | Условие | Возврат `_close_roundtrips` | Последствия |
|-------|---------|------------------------------|-------------|
| Полный успех | Все SELL-группы нашли соответствие, UPDATE прошли | `closed = N, direct + fuzzy = N` | Все позиции закрыты по реальной цене |
| Частичный успех (норма) | Часть SELL-групп не нашла OPEN (нет такого position_key, или закрыто 3B раньше) | `closed < processed, skipped > 0` | Норма работы — большинство SELL-групп не имеют соответствующих OPEN |
| Fallback fuzzy | Exact-match не нашёл, fuzzy нашёл | `fuzzy > 0`, по этим строкам `confidence=LOW, pnl_status=ESTIMATED` | Закрытие выполнено, но с пониженной уверенностью |
| Падение середины | Любой `execute` бросил исключение | exception пробрасывается, Python-процесс падает | Транзакция откатывается; следующий cron-запуск через час начнёт всё заново |
| Пустой ввод | SELECT не вернул SELL-сделок | `processed = 0` | NoOp, лог пишется, exit 0 |

Из наблюдений на проде (последний прогон 2026-05-28 12:16): typical pattern — `SELL groups processed: ~22000, Roundtrips CLOSED: ~10, skipped: ~22000`. Большинство SELL-сделок не имеют соответствующих OPEN, потому что соответствующая позиция уже закрыта шагом 3B по резолюции рынка раньше, чем сработал шаг 3C.

---

## 10. Зависимости

### Upstream

- **Шаг 2B** — `whale_trades` должна содержать SELL-события. Без записей с `side='sell'` шаг 3C выдаёт пустой результат. Объём 3C-закрытий **прямо пропорционален SELL-инжесту в 2B**: расширение polling-охвата или появление активных SELL-трейдеров (включая MM-китов) даёт всплеск объёма 3C без изменений в самом close-pipeline.
- **Шаг 3A** — `whale_trade_roundtrips` должна содержать OPEN-roundtrip-ы. Без OPEN — 3C не находит совпадений.
- **Шаг 2A** — `whales` для контекста (FK), но не блокирующая зависимость.

### Downstream

- **Шаг 4** (`update_whale_pnl_from_roundtrips`) — читает все CLOSED-roundtrip-ы (включая закрытые 3C) и агрегирует в `whales`. Связь асинхронная через БД, race-окно (см. §14 и RED FLAG #2).
- **Materialized views** (`paper_simulation_pnl`, `whale_pnl_summary`) — JOIN-ятся на `whale_trade_roundtrips`, рефрешатся каждые 2 часа отдельным cron'ом.

### Параллельная ветвь закрытия

**Шаг 3B** — закрывает те же OPEN-roundtrip-ы по другой логике (по резолюции рынка). 3B и 3C конкурируют за один и тот же набор OPEN. В норме 3B обрабатывает большинство, 3C — только те, где кит вышел через SELL до резолюции (см. RED FLAG #3).

### External

Никаких external API. Только PostgreSQL через `DATABASE_URL` из `.env`.

---

## 11. Наблюдаемость

### Логи

`logger = print` (`roundtrip_builder.py:38`) — все логи через `print()`, без структурированного формата. Stdout host-cron'а перенаправляется в `/root/polymarket-bot/logs/close_sell_cron.log` (append-mode).

Ключевые сообщения за итерацию:
- `ROUNDTRIP BUILDER (close mode) - Starting`
- `[1/2] Fetched N SELL groups`
- `[2/2] _close_roundtrips: processed=N, closed=M, direct=X, fuzzy=Y, skipped=Z`
- Для каждого решения матчинга: `INFO: close_match_direct ...` или `INFO: close_match_skipped ...` или `WARNING: close_match_fuzzy ...`
- `Database stats: {'CLOSED': N, 'OPEN': M, 'total': X}`
- `ROUNDTRIP BUILDER (close mode) - DONE (exit 0)`

Уровни INFO/WARNING присутствуют как префиксы строк, но это просто `print`-строки, не настоящий logging.Level — алертинг по уровням затруднён.

### Метрики

Не экспортируются. Prometheus/Statsd-эндпоинтов нет.

### Heartbeat

Отдельного heartbeat-файла для 3C нет (host-cron не нуждается в docker-healthcheck). Признак живости — свежесть последней строки в `close_sell_cron.log` (последний exit 0 моложе 1 часа). Если cron не отрабатывает — лог застывает, но автоматического алерта на это нет.

### Ротация логов

`>> /root/polymarket-bot/logs/close_sell_cron.log 2>&1` — append без ограничения размера (на момент верификации файл 54 MB). Logrotate-конфигурация в скоупе не подтверждена. На длинной дистанции файл растёт безгранично (та же проблема, что RF12 в 3B).

---

## 12. Объём 3C в production

**Доля SELL-закрытий низкая и инжест-зависимая.** Объём 3C напрямую определяется притоком SELL-сделок в `whale_trades` (шаг 2B), который, в свою очередь, зависит от состава отслеживаемых китов и их торговой активности.

**Свойства объёма:**
- **Низкая базовая линия** — типично десятки SELL-закрытий в сутки в спокойном режиме. Большинство OPEN закрывается раньше шагом 3B по резолюции рынка.
- **Высокая волатильность** — отдельный активный SELL-трейдер (особенно market-maker с высокой частотой продаж) может в одиночку дать всплеск в сотни/тысячи закрытий в сутки, не отражающий структурного изменения 3C.
- **Зависимость от governance** — добавление/исключение китов в шаге 6 (`copy_status`) меняет состав 2B-инжеста и, как следствие, объём 3C. MM-киты, по которым происходит самосвязанная BUY/SELL-торговля без edge'а, должны исключаться через `copy_status='excluded' с exclusion_reason='auto_market_maker'`.

Из этого следует: **объём 3C — не индикатор корректности pipeline и не структурная характеристика топологии закрытий**. Любые количественные оценки доли SELL vs SETTLEMENT-закрытий имеют смысл только при фиксированном составе `copy_status` и должны интерпретироваться с учётом MM-китов.

---

## 13. RED FLAGs

**RED FLAG #1 — `fees_usd` игнорируется в `net_pnl_usd`.**
Формула P&L: `gross_pnl_usd = net_pnl_usd = (close_price - open_price) * open_size_usd`. Поле `fees_usd` остаётся `0` (хардкод, lines 479, 774). UPDATE проставляет `net_pnl_usd = gross_pnl_usd` — два поля всегда равны. Для paper-аналитики, где комиссии = 0, это нормально; при будущем переходе на real execution с реальными fees `net_pnl_usd` будет некорректным. Та же RF существует и в шаге 3B (RF9). **Статус: Known Limitation.**

**RED FLAG #2 [P1 — материализован] — Асинхронный race между 3C и шагом 4.**
Шаг 4 (`update_whale_pnl_from_roundtrips`) и шаг 3C запускаются из **разных cron-задач с разными расписаниями**:
- Шаг 4: `run_settlement.sh`, `0 */2 * * *` (каждые 2 часа, минута 00).
- Шаг 3C: `run_close_sell.sh`, `15 * * * *` (каждый час, минута 15).

Метод `run_close_positions()` (3C) **не вызывает** `_update_whales_pnl()`. Это значит, что:
- 3C закрывает roundtrip в `whale_trade_roundtrips` в `:15` любого часа.
- `whales` агрегаты (`total_pnl_usd`, `win_rate`, etc.) **не пересчитываются** в этот момент — они пересчитаются только при следующем запуске шага 4 в `:00` ближайшего чётного часа.
- Это создаёт временное расхождение между `whale_trade_roundtrips` (актуально) и `whales` (отстаёт до 2 часов).

Дополнительно: в чётные часы окно пересекается — шаг 4 в `:00` агрегирует roundtrip-ы, шаг 3C в `:15` того же часа добавляет новые CLOSED. Эти CLOSED не попадут в агрегацию текущего часа, попадут только в следующую через 2 часа. Атомарных гарантий, что 3C не пишет в roundtrip, который шаг 4 уже прочитал, нет.

**Статус: Known Limitation в проде.** Race не приводит к потере данных (только к временному lag в `whales`), но создаёт окно неконсистентности для downstream-потребителей `whales` (Weekly AI шага 5, materialized views). Полное устранение требовало бы синхронизации расписаний 3C и 4 или вызова шага 4 изнутри 3C-cron'а.

**RED FLAG #3 — Race между 3B и 3C за один OPEN-roundtrip.**
Шаги 3B (`0 */2 * * *`, минута 00) и 3C (`15 * * * *`, минута 15) могут оба претендовать на закрытие одного и того же OPEN-roundtrip. Сценарий: кит купил позицию → 3A создал OPEN → рынок резолвится → 3B на `:00` закрывает позицию по бинарной цене 1.0/0.0 (`close_type='SETTLEMENT_*'`). Если кит при этом ещё и продал позицию через SELL до резолюции, 3C на `:15` попытается закрыть тот же roundtrip, но WHERE-клауза `rt.status='OPEN'` в SELECT-фазе уже не найдёт его — он CLOSED. Защита есть, но через SELECT-фильтр, а не через явный UPDATE-guard. Race-окно — минуты между SELECT и UPDATE 3C-итерации; в текущей версии не материализовался.

Обратный сценарий: 3C на `:15` закрыл по SELL раньше, чем 3B на `:00` следующего чётного часа. 3B при сборке кандидатов фильтрует по `rt.status='OPEN'` — уже-CLOSED 3C-roundtrip не подхватит. Тоже защищено через SELECT, не UPDATE-guard. **Статус: латентная защита через SELECT-фильтр, материального бага не наблюдалось.**

---

## 14. Результат шага

После успешного выполнения одной итерации `run_close_positions()`:

- Часть OPEN-roundtrip-ов, по которым кит вышел через SELL до резолюции рынка, переведены в `status='CLOSED'` с `close_type='SELL'`.
- Каждый закрытый roundtrip имеет проставленные `close_price` (реальная цена SELL), `close_size_usd`, `close_trade_id`, `close_side='sell'`, `closed_at` (момент SELL-сделки), `matching_method` (`DIRECT_SELL`/`FUZZY_FLIP`), `matching_confidence` (`HIGH`/`LOW`), `pnl_status` (`EXACT`/`ESTIMATED`).
- `gross_pnl_usd = net_pnl_usd = (close_price - open_price) * open_size_usd`. Без fee-вычета (RF1).
- Большинство SELL-сделок не находит соответствия в OPEN (либо нет такого position_key, либо позиция уже закрыта 3B раньше) — это нормальный режим работы.
- Сырой `whale_trades` не модифицируется.
- `whales` агрегаты НЕ обновляются в этой итерации.

**Состояние позиции в магистрали:** позиция, по которой кит продал свою долю, переходит в финальное состояние с реальной ценой выхода и точным P&L. Дальнейшая жизнь позиции в системе — read-only материал для downstream-агрегации.

### Связь со следующим шагом магистрали

**Шаг 4 — `update_whale_pnl_from_roundtrips`** запускается **из другого cron'а** (`run_settlement.sh`, `0 */2 * * *`), не из 3C. Это означает:

- **Триггер шага 4 — независимый от 3C**: разные cron-расписания, разные часы запуска. Шаги 3C и 4 не запускаются последовательно в одной bash-задаче.
- **Передача данных между шагами — через БД с временным лагом**: 3C пишет в `whale_trade_roundtrips`, шаг 4 читает оттуда же, но **до 2 часов спустя**.
- **Атомарность отсутствует**: 3C и 4 — две полностью независимые транзакции на стороне БД, в разных процессах, в разное время. Если 3C закоммитил, а 4 ещё не запустился — `whale_trade_roundtrips` обновлены, `whales` агрегаты ещё нет. Это создаёт окно неконсистентности до 2 часов (см. RED FLAG #2).
- **Сравнение с 3B**: шаг 3B вызывает шаг 4 в той же bash-задаче (`run_settlement.sh:38-39`), через 1-2 секунды после settlement. Для 3C такого вызова нет.

**Параллельная ветка закрытия — шаг 3B (доминирующий механизм).** Большинство закрытий идёт через 3B. 3C обрабатывает только позиции, где кит фактически продал до резолюции и SELL попал в `whale_trades` через 2B. Объём 3C-закрытий волатилен и зависит от состава отслеживаемых китов (см. §12).

---

## 15. Краткая бизнес-формула шага

```
ВХОД: каждый час в :15
  │
  ├── host-cron: 15 * * * * → run_close_sell.sh
  │     │
  │     ├── source .env, cd /root/polymarket-bot
  │     └── python3 -m src.strategy.roundtrip_builder --close
  │
  ▼
run_close_positions()
  │
  ├── [1/2] _fetch_and_group_sell_trades()
  │     │
  │     └── SELECT * FROM whale_trades WHERE side='sell'
  │         → группировка по (wallet, market, outcome)
  │
  ├── [2/2] _close_roundtrips(sell_groups)
  │     │
  │     ├── для каждой группы:
  │     │     ├── Проход 1 — exact-match:
  │     │     │     SELECT rt.* FROM whale_trade_roundtrips rt
  │     │     │     JOIN whale_trades wt ON position_key match
  │     │     │     WHERE rt.status='OPEN' AND wt.traded_at > rt.opened_at
  │     │     │     ORDER BY wt.traded_at DESC, wt.id DESC (window function)
  │     │     │
  │     │     ├── если не нашли — Проход 2 — fuzzy-fallback:
  │     │     │     SELECT по (wallet, market, outcome) без position_key
  │     │     │     WHERE wt.outcome = rt.outcome AND wt.traded_at > rt.opened_at
  │     │     │     ORDER BY sell_traded_at DESC LIMIT 1
  │     │     │
  │     │     └── если нашли (любой проход):
  │     │           UPDATE whale_trade_roundtrips
  │     │           SET status='CLOSED', close_type='SELL',
  │     │               close_price, close_size_usd, close_trade_id, close_side='sell', closed_at,
  │     │               matching_method = 'DIRECT_SELL' or 'FUZZY_FLIP',
  │     │               matching_confidence = 'HIGH' or 'LOW',
  │     │               pnl_status = 'EXACT' or 'ESTIMATED',
  │     │               gross_pnl_usd = net_pnl_usd = (close_price - open_price) * open_size_usd,
  │     │               updated_at = NOW()
  │     │           WHERE id = :roundtrip_id
  │     │
  │     └── return {processed, closed, direct, fuzzy, skipped}
  │
  ▼
ВЫХОД: whale_trade_roundtrips → OPEN→CLOSED (close_type='SELL')
   ↓ (асинхронно, до 2 часов лаг — другой cron)
[шаг 4 — update_whale_pnl_from_roundtrips, агрегирует в whales]
```

---

## 16. Историческое наследие: 530 legacy FLIP + 160 sentinel backfill

В таблице `whale_trade_roundtrips` присутствуют две группы строк с `close_type='SELL'`, не созданные текущим production-pipeline 3C:

**530 legacy FLIP-строк (pre-TRD-443):**
- `matching_method ∈ {'FLIP'}`, `pnl_status ∈ {'CONFIRMED', 'LEGACY_INVALID'}`.
- Созданы более ранней DORMANT-версией close-механизма до его деактивации (исторически — Phase 2B и более ранние).
- Помечены марker'ом `is_legacy_close=TRUE` через миграцию `phase3_006` для отличия от текущего pipeline.
- 75 из 530 имеют `pnl_status='LEGACY_INVALID'` (миграция `phase3_007a`) — pre-TRD-443 расчёты P&L признаны невалидными по результатам forensics.
- Не модифицируются текущим 3C. Должны интерпретироваться как archival data; их `net_pnl_usd` не следует использовать в downstream-агрегации без явной фильтрации `is_legacy_close=FALSE`.

**160 sentinel backfill-строк (TRD-443 reactivation):**
- `matching_method = 'MANUAL_RUN_TRD443'`, `pnl_status = 'EXACT'`, `matching_confidence = 'HIGH'`.
- Созданы одноразовым ручным backfill-прогоном `_close_roundtrips()` с переопределённым `sentinel_method='MANUAL_RUN_TRD443'` в момент реактивации pipeline (2026-05-19).
- Покрывают исторические SELL-сделки, для которых на момент реактивации существовали соответствующие OPEN-roundtrip-ы.
- Сумма `net_pnl_usd` по этим 160 строкам: $14,485.93 (по CHANGELOG TRD-443).
- Не воспроизводятся новыми итерациями pipeline (текущий код проставляет `DIRECT_SELL`/`FUZZY_FLIP`, не `MANUAL_RUN_TRD443`).

Whitelist'ы `matching_method` и `pnl_status` расширены миграциями `phase3_007` и `phase3_007a` именно для поддержки обоих legacy-наборов, без необходимости модификации текущего pipeline.