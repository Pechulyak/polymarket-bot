# ШАГ 9 (paper-ветка P4). МАТЕРИАЛИЗАЦИЯ PAPER P&L

## Краткая характеристика (TL;DR)

Каждые 2 часа в :15 host-cron-задача `refresh_views.sh` обновляет три materialized view, которые и есть единственный источник paper P&L в системе: `whale_pnl_summary` (агрегированный P&L по каждому киту), `paper_portfolio_state` (одна строка — текущее состояние нашего виртуального портфеля), `paper_simulation_pnl` (наш P&L построчно, по одной paper-сделке). Наш результат по сделке не считается отдельным settlement-процессом — его «закрывает» косвенно сопоставление нашей paper-сделки с уже закрытой позицией кита: сколько заработал кит на этой позиции, столько же зарабатываем мы, но в пропорции нашего размера к размеру кита.

Это финальный шаг paper-ветки. Дальше paper-данные только читаются — дашбордом и ручной аналитикой governance-окна (шаг 5). «Следующего шага» у paper-ветки нет.

Объект здесь — уже не отдельная paper-сделка, а **портфель** и **сводка по китам**: множество paper-сделок и закрытых позиций китов сворачивается в денормализованные P&L-таблицы для дешёвого чтения.

---

## 1. Назначение шага

Перевод разрозненных записей (`paper_trades` без собственного P&L + закрытые позиции китов в `whale_trade_roundtrips`) в **готовые к чтению P&L-агрегаты трёх уровней**: построчно по сделке, целиком по портфелю, и по каждому киту. Без этого шага paper P&L существовал бы только как ad-hoc SQL с JOIN-ом и формулой пропорции — каждый раз заново.

Бизнес-смысл: «у каждой нашей paper-сделки есть посчитанный долларовый результат, у портфеля — текущий баланс и ROI, у каждого кита — его суммарный P&L; всё это готово к мгновенному чтению и не требует пересчёта на лету».

Ключевой принцип расчёта (стандарт PHASE4-004): наш результат пропорционален результату кита.

```
our_pnl = whale_pnl × (our_size / whale_size)
```

где `our_size` — наш Kelly-размер из paper-сделки, `whale_size` — размер открытия позиции кита, `whale_pnl` — итоговый P&L закрытой позиции кита.

---

## 2. Статус

**ACTIVE.** Все три view существуют в БД и наполнены (`pg_matviews.ispopulated = t` для всех трёх). Cron-задача отрабатывает штатно: последний успешный refresh на момент верификации — 2026-05-28 10:15, в логе все три view обновлены без ошибок. `REFRESH ... CONCURRENTLY` работает корректно (необходимые уникальные индексы присутствуют, см. §9).

Дата верификации: 2026-05-28.

Существенная оговорка, не влияющая на статус: примерно треть paper-сделок не попадает в P&L из-за отсутствия сопоставленной закрытой позиции кита (см. §13 RF1). Это свойство данных и логики JOIN, а не отказ инфраструктуры.

---

## 3. Исходные файлы

**Определения view:**
- Миграционных файлов с `CREATE MATERIALIZED VIEW` для этих трёх view **в репозитории нет**. Views созданы в БД напрямую; источник истины — `pg_matviews.definition`. Это hygiene-долг (определения вне git), фиксируется в §16.

**Оркестрация и расписание:**
- `scripts/refresh_views.sh` — три последовательных `REFRESH MATERIALIZED VIEW CONCURRENTLY` через `docker exec polymarket_postgres psql`
- crontab хоста: `15 */2 * * * /root/polymarket-bot/scripts/refresh_views.sh >> /root/polymarket-bot/logs/view_refresh.log 2>&1`

**DDL источников данных:**
- `scripts/migration_whale_trade_roundtrips.sql` — DDL `whale_trade_roundtrips` (описана в шаге 3A)
- `paper_trades` — DDL вне скоупа этого шага (описана в шаге 7)
- `strategy_config` — ключи `our_bankroll`, `bankroll_reset_at`

---

## 4. Контейнер

Собственного docker-контейнера нет. Refresh выполняется в контейнере `polymarket_postgres` по запросу host-cron через `docker exec` — по той же модели, что шаги 3B/4 (`run_settlement.sh`). Долгоживущего процесса не существует: три psql-вызова, завершение.

Имя контейнера hardcoded в `refresh_views.sh`. Соединение — `psql -U postgres -d polymarket` без дополнительных параметров.

---

## 5. Триггер запуска и расписание

| Параметр | Значение |
|----------|----------|
| Тип триггера | host cron |
| Cron expression | `15 */2 * * *` |
| Время срабатывания | :15 каждого чётного часа — 00:15, 02:15, 04:15, … |
| Период | 2 часа |
| Позиция относительно settlement | refresh запускается через 15 минут после settlement-окна `run_settlement.sh` (`0 */2 * * *`), чтобы читать уже актуальные закрытые roundtrip-ы |
| Альтернативные источники refresh | не обнаружено — только `refresh_views.sh` |

15-минутный сдвиг от settlement — намеренный: к моменту refresh шаги 3B/4 уже успели закрыть позиции китов и пересчитать их P&L, так что view видят свежие данные.

---

## 6. Алгоритм шага

`refresh_views.sh` выполняет три независимых REFRESH строго последовательно, в порядке: `whale_pnl_summary` → `paper_portfolio_state` → `paper_simulation_pnl`. Условной логики между ними нет; каждый REFRESH самодостаточен и пересчитывает свой view с нуля из базовых таблиц.

### Reset-окно (общее для двух paper-view)

Оба paper-view (`paper_simulation_pnl`, `paper_portfolio_state`) считают P&L **не за всю историю**, а начиная с момента последнего сброса виртуального банка. Граница берётся из `strategy_config.bankroll_reset_at` (хранится как Unix-timestamp), при отсутствии ключа — fallback на `2026-04-04 00:00:00`. В расчёт попадают только paper-сделки с `created_at > reset_ts`. Механика самого сброса (кто и когда меняет `bankroll_reset_at`) — вне скоупа paper-ветки.

### whale_pnl_summary — агрегат по китам

`whales LEFT JOIN whale_trade_roundtrips` по нормализованному (`lower()`) `wallet_address`, с фильтром `copy_status IN ('paper','tracked','excluded')`, группировка по киту. Для каждого кита считаются: число roundtrip-ов (всего / closed / open), wins/losses (по CLOSED с `net_pnl_usd > 0` и `<= 0`), суммарный и средний P&L по CLOSED, плюс производные (win_rate, profit_factor, объём и т.п.). LEFT JOIN означает: кит без единого roundtrip всё равно присутствует в view с нулевыми агрегатами. Reset-окно здесь **не применяется** — это сводка по китам за всю историю, не по нашему портфелю.

### paper_simulation_pnl — наш P&L построчно

Двухфазная логика. Сначала CTE `matched`: каждая paper-сделка (после reset) сопоставляется с roundtrip-ом кита через INNER JOIN по тройке `(market_id, lower(wallet_address), side ↔ open_side)`. При нескольких подходящих roundtrip-ах выбирается один — ближайший по времени открытия к нашей сделке (`DISTINCT ON (paper_trade.id)` + сортировка по модулю разницы `opened_at − created_at`). Затем по сопоставленной паре считается наш результат:

```
our_pnl_usd = CASE
    WHEN rt.status = 'CLOSED' AND rt.open_size_usd > 0
    THEN rt.net_pnl_usd × our_size / rt.open_size_usd
    ELSE NULL
END
```

Для незакрытых позиций кита (`status='OPEN'`) наш P&L равен NULL, а `result` помечается `'OPEN'`; для закрытых — `'WIN'`/`'LOSS'` по знаку P&L кита.

### paper_portfolio_state — состояние портфеля одной строкой

Та же логика сопоставления, что в `paper_simulation_pnl`, но результаты сворачиваются в единственную строку:

- `initial_bankroll` — из `strategy_config.our_bankroll` (fallback `1000`)
- `realized_pnl` — сумма наших P&L по CLOSED-позициям, с защитой деления `NULLIF(whale_size, 0)`
- `current_balance = initial_bankroll + realized_pnl`
- `allocated_capital` — сумма наших размеров по OPEN-позициям
- `available_capital = current_balance − allocated_capital`
- счётчики open/closed, wins/losses, `win_rate`, `roi_pct`, `refreshed_at = now()`

---

## 7. Формат входных данных

| Источник | Роль | Ключевые поля |
|----------|------|---------------|
| `paper_trades` | наши paper-сделки | `id`, `market_id`, `whale_address`, `side`, `kelly_size` (наш размер), `size_usd` (размер кита), `price`, `outcome`, `created_at`, `kelly_fraction` |
| `whale_trade_roundtrips` | позиции китов | `market_id`, `wallet_address`, `open_side`, `status`, `open_size_usd`, `net_pnl_usd`, `opened_at`, `closed_at`, `close_type`, `close_price` |
| `whales` | метаданные китов (для summary) | `wallet_address`, `copy_status`, `whale_category`, `estimated_capital` |
| `strategy_config` | параметры | `our_bankroll`, `bankroll_reset_at` |

Сопоставление `paper_trades ↔ whale_trade_roundtrips` — по `(market_id, lower(wallet_address), side↔open_side)`; `side` в `paper_trades` хранится как текст `BUY`/`SELL`, сопоставляется с `open_side` напрямую.

---

## 8. Формат выходных данных

Три materialized view. Потребители — Grafana-дашборд paper P&L и ручная SQL-аналитика governance-окна (шаг 5, `whale_audit.sql` / manual SELECT). Прямого программного downstream-консьюмера (контейнера, который читал бы эти view и что-то писал) нет.

- `paper_simulation_pnl` — одна строка на сопоставленную paper-сделку (4350 строк на момент верификации)
- `paper_portfolio_state` — ровно одна строка (снимок портфеля)
- `whale_pnl_summary` — одна строка на кита из paper/tracked/excluded (94 строки)

---

## 9. Записи в БД

Шаг **не пишет в базовые таблицы**. Единственный эффект — перезапись содержимого трёх materialized view командой REFRESH.

**paper_simulation_pnl** — ключевые колонки: `paper_trade_id`, `market_id`, `whale_address`, `side`, `outcome`, `entry_price`, `our_size_usd`, `whale_trade_size_usd`, `whale_roundtrip_size_usd`, `entry_date`, `position_status`, `close_type`, `close_price`, `close_date`, `our_pnl_usd`, `whale_pnl_usd`, `result`, `market_category`.

**paper_portfolio_state** — колонки: `initial_bankroll`, `realized_pnl`, `current_balance`, `allocated_capital`, `available_capital`, `open_positions_count`, `closed_positions_count`, `wins`, `losses`, `win_rate`, `roi_pct`, `refreshed_at`.

**whale_pnl_summary** — колонки: `wallet_address`, `copy_status`, `whale_category`, `estimated_capital`, `total_roundtrips`, `closed_roundtrips`, `open_roundtrips`, `wins`, `losses`, `total_pnl`, `avg_pnl`, плюс производные (`win_rate`, `profit_factor`, объём, средний размер, даты первой/последней активности). Наличие колонки `copy_status` позволяет downstream-консьюмеру отфильтровать excluded-китов при необходимости.

**Уникальные индексы (обязательны для CONCURRENTLY):**

| View | Индекс | Колонки |
|------|--------|---------|
| `paper_simulation_pnl` | `idx_simulation_pnl_ptid` | `(paper_trade_id)` UNIQUE |
| `whale_pnl_summary` | `idx_whale_pnl_summary_wallet` | `(wallet_address)` UNIQUE |
| `paper_portfolio_state` | `idx_paper_portfolio_state_uniq` | `(initial_bankroll)` UNIQUE |

Idempotency: REFRESH полностью детерминирован относительно состояния базовых таблиц — повторный запуск без изменения источников даёт тот же результат.

---

## 10. Условия успеха / частичного успеха / неуспеха

**Успех:** все три REFRESH завершились, view наполнены, в логе строка `All views refreshed OK`.

**Частичный успех:** `set -e` в скрипте прерывает выполнение на первом упавшем REFRESH — то есть строгого «частичного» состояния по дизайну нет. Но возможен **семантически частичный** результат при штатном успехе: paper-сделки без сопоставленного roundtrip-а молча отсутствуют в `paper_simulation_pnl`, а сделки по ещё не закрытым позициям имеют `our_pnl_usd = NULL`. Технически refresh успешен, фактически P&L неполон (см. §13 RF1).

**Неуспех:** любой REFRESH вернул ошибку → `set -e` останавливает скрипт, последующие view не обновляются и остаются со **старым** содержимым (CONCURRENTLY не разрушает предыдущую версию при сбое). Внешне это выглядит как «часть view свежая, часть устаревшая» до следующего успешного прогона. Ошибка попадает в `view_refresh.log` через `2>>`.

---

## 11. Зависимости

**Upstream:**
- Шаг 7 (paper-ветка P1) — наполняет `paper_trades`
- Шаги 3A/3B/4 — создают и закрывают `whale_trade_roundtrips`; именно от их своевременности зависит, появится ли у нашей сделки сопоставленный CLOSED-roundtrip
- `strategy_config` — `our_bankroll`, `bankroll_reset_at`

Связь с upstream — **асинхронная через таблицы**: refresh читает то, что есть в `paper_trades` и `whale_trade_roundtrips` на момент запуска. Между записью данных и их появлением во view — задержка до 2 часов (период cron) плюс лаг settlement.

**Downstream:**
- Grafana-дашборд paper P&L
- Ручная SQL-аналитика governance-окна (шаг 5)

Downstream-связь односторонняя read-only — потребители только читают view, обратной записи нет.

---

## 12. Наблюдаемость

**Логи:** `refresh_views.sh` пишет в `/root/polymarket-bot/logs/view_refresh.log` (и параллельно в `/var/log/polymarket/view_refresh.log` внутри скрипта) старт, по строке на каждый успешно обновлённый view, и финальную `All views refreshed OK`. stderr каждого psql-вызова перенаправлен в тот же лог.

**Состояние наполнения:** `pg_matviews.ispopulated` показывает, наполнен ли каждый view (все три = `t`).

**Метрики/алерты:** не экспортируются. Нет Prometheus/Statsd, нет алерта на «refresh упал» или «match rate просел». Обнаружение проблемы — только через чтение лога или прямой SQL.

**Что наблюдатель НЕ видит:**
- Долю сопоставленных сделок (match rate) — нигде не логируется, вычисляется только ручным COUNT.
- Факт, что часть сделок выпала из P&L — внешне refresh «успешен».
- Возраст данных во view между прогонами — `refreshed_at` есть только в `paper_portfolio_state`, для двух других view нет временной метки последнего refresh внутри самого view.

---

## 13. Особые случаи и риски (RED FLAGs)

**RF1 [data — материализован] — около трети paper-сделок не попадает в P&L.**
INNER JOIN в CTE `matched` требует существования сопоставленного roundtrip-а кита. На момент верификации: 4350 строк в `paper_simulation_pnl` против 6731 в `paper_trades` — match rate ≈ 64.6%, то есть ~2381 сделки (35%) не отражены в paper P&L. Причины: (а) roundtrip кита ещё не создан шагом 3A (лаг до 2 ч); (б) roundtrip создан, но `status='OPEN'` → сделка попадает в view, но `our_pnl_usd=NULL`; (в) отсутствие сопоставления по тройке ключей вообще (расхождение `market_id`, нормализованного `wallet_address` или `side`↔`open_side`). Это конкретная материализация RF6 шага 7 (нет FK `paper_trades → whale_trade_roundtrips`): целостность держится на JOIN-е по бизнес-ключам, и при любом промахе сделка тихо исчезает из портфельного P&L. Следствие: `paper_portfolio_state.realized_pnl` и `current_balance` отражают P&L **неполного** портфеля, и это не сигнализируется.

**RF2 [data — latent] — `our_size = NULL` обнулит вклад сделки без следа.**
Формула `whale_pnl × our_size / whale_size` при `our_size IS NULL` (Kelly-размер) вернёт NULL, и через `COALESCE(SUM(...), 0)` такая сделка молча выпадет из `realized_pnl`. Сейчас защита данных есть на уровне источника: все 6731 записи `paper_trades` имеют непустой `kelly_size` (0 NULL, 0 нулевых). Но это **upstream-зависимость от RF1 шага 7** (`kelly_size=NULL` при `estimated_capital=0`): как только trigger шага 7 произведёт первую NULL-запись, она беззвучно исказит портфельный P&L. Сам view от NULL не падает — он его «проглатывает», что и опасно.

**RF3 [config — latent] — fallback `our_bankroll=1000` против prod `100`.**
Оба источника bankroll — view `paper_portfolio_state` и trigger шага 7 — при отсутствии `strategy_config.our_bankroll` деградируют к литералу `1000`, тогда как фактическое prod-значение `100`. Если ключ `our_bankroll` будет удалён или переименован, оба места синхронно переключатся на `1000`, исказив `current_balance`, `roi_pct` и Kelly-sizing одновременно и **согласованно** — то есть расхождение будет внутренне непротиворечивым и оттого труднее обнаружимым. Сейчас ключ присутствует (`100.00`), риск латентный.

**RF4 [arch — материализован] — stale-данные до 2 часов.**
Между прогонами cron view не обновляются. Grafana и ручная аналитика governance-окна (шаг 5) в худшем случае видят P&L возрастом до 2 ч (период refresh) плюс лаг settlement шагов 3B/4. Поскольку решения шага 6 (перевод кита paper↔tracked↔excluded) опираются в т.ч. на эти view, governance-решение может приниматься по картине двухчасовой давности. Для недельного ритма governance это приемлемо, но должно учитываться при ad-hoc решениях в середине недели.

**RF5 [arch — latent] — уникальный индекс `paper_portfolio_state` по `initial_bankroll`.**
View по дизайну содержит одну строку, уникальность задана по значению `initial_bankroll`. Пока bankroll стабилен — CONCURRENTLY работает штатно. Краевой случай: если после reset не окажется ни одной сопоставленной CLOSED-позиции, агрегатная часть всё равно вернёт одну строку (агрегаты без GROUP BY дают строку с нулями), так что «пустого» результата здесь не возникает — индекс остаётся валидным. Риск проявился бы только при изменении схемы view на множество строк с одинаковым `initial_bankroll`: тогда уникальный индекс начнёт отвергать CONCURRENTLY-refresh. Низкий приоритет, привязан к будущему рефакторингу.

---

## 14. Результат шага и связь с остальной картой

После успешного прогона:
- `paper_simulation_pnl` — построчный P&L по всем сопоставленным paper-сделкам после reset.
- `paper_portfolio_state` — одна строка с текущим балансом, realized P&L, ROI, счётчиками позиций.
- `whale_pnl_summary` — сводный P&L по каждому киту из paper/tracked/excluded.

**Состояние объекта:** paper-портфель и сводка по китам достигли актуального материализованного состояния. Это **финальная точка paper-ветки** — дальнейших шагов, изменяющих эти данные, нет.

**Связь с картой.** Шаг 9 замыкает paper-ветку на governance-контур: его view читаются на шаге 5 как часть обоснования решений шага 6 (перевод китов между статусами). Таким образом paper-ветка не имеет линейного «следующего шага», но её выход возвращается в цикл governance — оператор смотрит на paper P&L, принимает решение по китам, новое решение меняет состав paper-китов, и следующая порция paper-сделок снова проходит P1→…→P4. Согласованность с шагом 5 усилена общим принципом «POST-RESET»: и `whale_audit.sql` шага 5, и paper-view считают результат от точки сброса банка, а не за всю историю.

---

## 15. Краткая бизнес-формула шага

```
ТРИГГЕР: host cron 15 */2 * * * → refresh_views.sh
  │
  ├── reset_ts = strategy_config.bankroll_reset_at  (fallback 2026-04-04)
  │
  ├── REFRESH whale_pnl_summary
  │     whales LEFT JOIN roundtrips (paper/tracked/excluded)
  │     → P&L-сводка на кита (за всю историю)
  │
  ├── REFRESH paper_portfolio_state
  │     paper_trades (created_at > reset_ts)
  │       INNER JOIN ближайший по времени roundtrip кита
  │     realized_pnl = Σ [ whale_pnl × our_size / NULLIF(whale_size,0) ]  по CLOSED
  │     current_balance = initial_bankroll + realized_pnl
  │     → одна строка состояния портфеля
  │
  └── REFRESH paper_simulation_pnl
        та же сопоставка, без свёртки
        our_pnl_usd = whale_pnl × our_size / whale_size   (только CLOSED, whale_size>0)
                    = NULL                                  (OPEN или нет матча)
        → одна строка на сопоставленную сделку

ПОТРЕБИТЕЛИ: Grafana, ручная аналитика шага 5 (read-only)
СЛЕДУЮЩЕГО ШАГА НЕТ — финал paper-ветки
```

---

## 16. Открытые вопросы

Определения трёх materialized view отсутствуют в git (созданы в БД напрямую) — единственный источник истины сейчас `pg_matviews.definition`. Восстановление их как версионируемых миграций — отдельная hygiene-задача, вне скоупа описания paper-ветки.
