# ШАГ 2A. РЕГИСТРАЦИЯ / ОБНОВЛЕНИЕ КИТА В ТАБЛИЦЕ `whales`

## Краткая характеристика (TL;DR)

Шаг 2 — точка ветвления магистрали на две независимые параллельные ветви:
- **Шаг 2A** — регистрация / обновление **кита** в таблице `whales` (per-address)
- **Шаг 2B** — запись **сделки** в таблице `whale_trades` (per-trade), описывается отдельным документом

### Шаг 2A в бизнес-нотации

Каждые **60 секунд** контейнер `whale-detector` берёт **до 500 свежих сделок** Polymarket, полученных на шаге 1, и группирует их **по адресу трейдера**. Из всех уникальных адресов выбираются только те, у кого в текущем окне набралось **не менее 10 сделок** — это и есть кандидаты на роль «кита». Для каждого такого адреса считаются краткие метрики активности (объём, средний размер сделки, активность за 3/7/30 дней), и **профиль кита** заносится в каталог `whales`: новый — как INSERT, ранее известный — как UPDATE существующей строки. Киты, ранее помеченные оператором как `excluded`, повторно не перезаписываются. Все остальные адреса (с менее чем 10 сделками в окне) в каталог не попадают, но их отдельные сделки всё равно записываются в `whale_trades` через параллельную ветку 2B.

Шаг 2A выполняется **только в discovery-цикле** (`_polymarket_poll_loop`). Targeted-циклы (paper / tracked / HOT / WARM) шаг 2A пропускают — они работают с уже зарегистрированными китами, выбранными из `whales` по `copy_status` или `tier`.

---

## 1. Назначение шага

Шаг обеспечивает **регистрацию новых китов и обновление метрик уже известных** в каталоге трейдеров `whales`. Без этого шага система не имеет представления о существовании конкретного трейдера: его сделки могут быть записаны (шаг 2B пишет `whale_trades` независимо), но без записи в `whales` трейдер не существует как сущность для downstream-логики (тиринг, копи-торговля, P&L-аналитика, FK-связи).

Бизнес-смысл: «увидели адрес → решили, достоин ли он быть в каталоге → если да, занесли или обновили его профиль».

---

## 2. Статус

**CONFIRMED-ACTIVE** для discovery-цикла (`_polymarket_poll_loop`): подтверждён триггер (docker-compose сервис `whale-detector`), точка входа (`run_whale_detection.py:189–194`), один производственный вызов `_save_whale_to_db()` в `_fetch_polymarket_whales()`.

**NOT-PRESENT** для targeted-циклов: вызов `_save_whale_to_db()` отсутствует во всех 6 проверенных точках (`_paper_poll_loop`, `_fetch_paper_whale_trades`, `_tracked_poll_loop`, `_fetch_tracked_whale_trades`, `WhalePoller.run_hot_polling`, `WhalePoller.run_warm_polling`). См. §11 (Зависимости).

Дата верификации: 2026-05-10.

---

## 3. Исходные файлы

**Основной модуль регистрации:**
`src/research/whale_detector.py` — методы `_fetch_polymarket_whales()` (`whale_detector.py:1427`), `_save_whale_to_db()` (`whale_detector.py:980–1057`), `_load_known_whales()` (`whale_detector.py:392`), dataclass `DetectedWhale` (`whale_detector.py:158`), dataclass `DetectionConfig` (`whale_detector.py:188–191`).

**Источник агрегации:**
`src/research/polymarket_data_client.py` — метод `aggregate_by_address()` (`polymarket_data_client.py:295–299`), dataclass `AggregatedTraderStats` (`polymarket_data_client.py:66–88`).

**Вспомогательные расчёты (вне `_save_whale_to_db()`, но в той же итерации):**
- `calculate_risk_score(...)` — вызывается на `whale_detector.py:1568–1574`
- `_calculate_qualification_path(...)` — вызывается на `whale_detector.py:1577–1584` (RED FLAG #3 в §13)

**Entry point контейнера:** `src/run_whale_detection.py:189–194` — инстанцирование `WhaleDetector` без callback `on_whale_detected`.

---

## 4. Контейнер

`whale-detector` — отдельный docker-compose сервис.
Команда запуска: `python src/run_whale_detection.py`.
Шаг 2A выполняется внутри того же процесса, что и шаг 1 и шаг 2B.

---

## 5. Триггер запуска и расписание

**Единственный триггер:** цикл `WhaleDetector._polymarket_poll_loop`, интервал **60 секунд**.

Шаг 2A — **вторая ветвь** в теле метода `_fetch_polymarket_whales()` (`whale_detector.py:1427`), вызываемого этим циклом. Первая ветвь — шаг 2B (запись сделок в `whale_trades`), описывается отдельным документом.

Targeted-циклы (`_paper_poll_loop` 30s, `_tracked_poll_loop` 300s, `WhalePoller.run_hot_polling` 4h, `WhalePoller.run_warm_polling` 24h) шаг 2A **не выполняют** — см. §11.

---

## 6. Алгоритм шага

### 6.1 Точка ветвления магистрали (на входе шага 2A)

После шага 1 имеется `trades: List[TradeWithAddress]` (до 500 элементов).
Этот список одновременно поступает в:
- **ветвь 2A** — агрегация по адресам и регистрация китов (этот документ)
- **ветвь 2B** — пер-сделочная запись в `whale_trades` (отдельный документ)

Ветви выполняются в одной итерации `_fetch_polymarket_whales()`. Порядок в коде: сначала пер-сделочный цикл 2B (`whale_detector.py:1462–1489`), затем пер-адресный цикл 2A (`whale_detector.py:1495–1620`). См. RED FLAG #4 в §13.

### 6.2 Стадия 1 — агрегация по адресам

1. На `whale_detector.py:1495` вызывается `aggregated = await self.polymarket_client.aggregate_by_address(limit=500, min_size_usd=quality_volume)` — но фактически метод получает на вход уже отфильтрованный список сделок шага 1; повторный fetch не выполняется (по знанию шага 1).
2. `aggregate_by_address()` (`polymarket_data_client.py:295–299`) проходит по сделкам, группирует их по адресу trader. Для каждого адреса формируется `AggregatedTraderStats`:
   - `total_trades` — счётчик: `+1` на сделку (`polymarket_data_client.py:322`)
   - `total_volume_usd` — сумма: `+= trade.size_usd` (`polymarket_data_client.py:323`)
   - `avg_trade_size_usd` — `total_volume_usd / Decimal(total_trades)` (`polymarket_data_client.py:335–336`)
   - `buy_count` / `sell_count` — счётчики по `trade.side` (`polymarket_data_client.py:325–328`)
   - `last_seen` — `max(текущий, trade.timestamp)` (`polymarket_data_client.py:330–331`)
   - `name` — из первой сделки адреса (`polymarket_data_client.py:317–319`)
3. **Фильтрации на этом уровне нет.** Возвращаются все агрегаты, включая адреса с одной сделкой.

### 6.3 Стадия 2 — итерация по агрегатам с gate

На `whale_detector.py:1501`: `for address, stats in aggregated.items():`

Для каждого `(address, stats)`:

1. **Gate `min_trades_for_quality`** (`whale_detector.py:1509`):
   ```
   if stats.total_trades < self.config.min_trades_for_quality:
       continue
   ```
   Значение по умолчанию: **10** (`whale_detector.py:188`).
   Не прошёл — переход к следующему адресу (в `whales` не пишется). RED FLAG #1 в §13: эта же проверка дублируется на `:1586`.

2. **Классификация новый/известный** (`whale_detector.py:1514`):
   ```
   is_known = address.lower() in self._known_whales
   ```
   `_known_whales` — in-memory `Set[str]`, перезаполняется при `start()` из БД запросом `SELECT wallet_address FROM whales WHERE qualification_status IN ('qualified', 'ranked', 'tracked')` (`whale_detector.py:402–408`). RED FLAG #5 в §13: статусы `none`, `paper`, `excluded` в set не попадают.

3. **Расчёт полей активности** (`whale_detector.py:1520–1543`):
   - `trades_last_3_days` — `min(stats.total_trades, 10)` если `last_seen` ≤ 3 суток назад, иначе 0 (`whale_detector.py:1531`)
   - `trades_last_7_days` — `min(stats.total_trades, 20)` если `total_trades >= 10` (`whale_detector.py:1541`)
   - `days_active` — `1` если есть активность, иначе `0` (`whale_detector.py:1532–1543`)
   RED FLAG #6 в §13: формулы huglo-эвристичные, не основаны на реальном распределении timestamps.

4. **Фолбэк `total_volume`** (`whale_detector.py:1547–1551`): если `stats.total_volume_usd == 0`, подставляется `stats.avg_trade_size_usd * Decimal(stats.total_trades)`.

5. **Формирование `DetectedWhale`** (`whale_detector.py:1553–1563`) — объект-DTO с полями для записи в `whales`. Поле `win_rate` инициализируется как `Decimal("0")` (всегда; помечено DEPRECATED, `whale_detector.py:158`).

6. **Расчёт `risk_score`** (`whale_detector.py:1568–1574`): вызов `calculate_risk_score(...)`. RED FLAG #2 в §13: использует deprecated `win_rate=0`, систематически смещён.

7. **Расчёт `qualification_path`** (`whale_detector.py:1577–1584`): вычисляется, но **не передаётся** в `_save_whale_to_db()` и не записывается в БД (колонка удалена в ARC-501). RED FLAG #3 в §13.

8. **Дублированный gate** (`whale_detector.py:1586`):
   ```
   if stats.total_trades >= self.config.min_trades_for_quality:
   ```
   В этой ветви — собственно регистрация:
   - `self._detected_whales[address.lower()] = whale` (`whale_detector.py:1587`) — кэш в памяти
   - `await self._save_whale_to_db(whale)` (`whale_detector.py:1588`) — **точка шага 2A**
   - если `not is_known`: `self._known_whales.add(address.lower())` (`whale_detector.py:1591`) и лог `polymarket_new_whale`
   - если `is_known`: лог `whale_updated`

9. **Callback** (`whale_detector.py:1614`):
   ```
   if self.on_whale_detected:
       await self.on_whale_detected(whale)
   ```
   В production callback **не подключён** (`run_whale_detection.py:189–194` не передаёт его). DORMANT-инфраструктура, RED FLAG #7 в §13.

### 6.4 Стадия 3 — запись в БД (тело `_save_whale_to_db()`)

`whale_detector.py:980–1057`:

1. `await self._ensure_database()` — ленивая инициализация SQLAlchemy session factory.
2. Лог `save_whale_to_db` с обрезанным адресом (первые 10 символов).
3. SQL-запрос `INSERT INTO whales (...) VALUES (...) ON CONFLICT (wallet_address) DO UPDATE SET ... WHERE whales.copy_status != 'excluded'` — `whale_detector.py:1005–1033`.
4. `session.execute(query, {...})` с 11 параметрами — `whale_detector.py:1034–1048` (полный список в §9).
5. `session.commit()` — `whale_detector.py:1050`.
6. На любой ошибке: `session.rollback()`, лог `save_whale_db_failed`, исключение наружу не пробрасывается (молчаливое поглощение).

**Защита от перезаписи исключённых китов:** `WHERE whales.copy_status != 'excluded'` (`whale_detector.py:1032`) — критичное условие. Если кит был помечен оператором как `excluded`, повторное обнаружение его в discovery **не сбросит** его статус и метрики.

---

## 7. Формат входных данных

**Из шага 1:**
- `trades: List[TradeWithAddress]` — список свежих сделок с lower-case адресами.

**Из конфигурации (`DetectionConfig`, `whale_detector.py:188–191`):**
- `min_trades_for_quality: int` — порог для регистрации, default `10`
- `quality_volume: Decimal` — минимальный размер сделки для агрегации, default `Decimal("1000")`

**Из состояния процесса:**
- `self._known_whales: Set[str]` — in-memory кэш известных адресов, заполнен на `start()`.
- `self._detected_whales: Dict[str, DetectedWhale]` — in-memory кэш текущей итерации.

---

## 8. Формат выходных данных

**Внутренний (в процессе):**
- `aggregated: Dict[str, AggregatedTraderStats]` — результат `aggregate_by_address()`.
- `whale: DetectedWhale` — DTO, передаваемый в `_save_whale_to_db()`.

**Внешний (в БД):**
- одна строка в таблице `whales` на каждого кита, прошедшего gate (см. §9).

**Что НЕ возвращается из `_save_whale_to_db()`:** метод не возвращает значение (`-> None`). Успех/неуспех виден только в логах. На уровне `_fetch_polymarket_whales()` нет проверки результата — следующий кит обрабатывается независимо.

---

## 9. Записи в БД

**Таблица:** `whales`
**Операция:** `INSERT INTO whales (...) VALUES (...) ON CONFLICT (wallet_address) DO UPDATE SET ... WHERE whales.copy_status != 'excluded'`
**Файл SQL:** `whale_detector.py:1005–1033`
**Файл параметров:** `whale_detector.py:1034–1048` (11 ключей)
**Commit:** `whale_detector.py:1050`

### Полный список изменяемых столбцов (14 шт)

| Колонка | Бизнес-смысл | INSERT / UPDATE | Источник значения | Файл:строка |
|---------|--------------|------------------|--------------------|-------------|
| `wallet_address` | уникальный адрес кошелька кита | INSERT (PK), key | `whale.wallet_address` | `whale_detector.py:1037` |
| `total_trades` | общее число сделок за период обзора | Both | `whale.total_trades` | `whale_detector.py:1038` |
| `total_volume_usd` | суммарный оборот кита в долларах | Both | `float(whale.total_volume)` | `whale_detector.py:1039` |
| `avg_trade_size_usd` | средний размер одной сделки кита | Both | `float(whale.avg_trade_size)` | `whale_detector.py:1040` |
| `risk_score` | оценка рискованности торговли кита | Both | `whale.risk_score` | `whale_detector.py:1041` |
| `qualification_status` | статус прохождения квалификации китом | Both | `whale.qualification_status` | `whale_detector.py:1042` |
| `trades_last_3_days` | число сделок за трое последних суток | Both | `whale.trades_last_3_days` | `whale_detector.py:1043` |
| `trades_last_7_days` | число сделок за последнюю неделю | Both | `whale.trades_last_7_days` | `whale_detector.py:1044` |
| `days_active_7d` | число активных дней за неделю | Both | `whale.days_active_7d` | `whale_detector.py:1045` |
| `days_active_30d` | число активных дней за месяц | Both | `whale.days_active_30d` | `whale_detector.py:1046` |
| `notes` | имя кита из данных API | Both | `whale.name or None` | `whale_detector.py:1047` |
| `last_active_at` | момент последней зафиксированной активности | Both | `NOW()` hardcoded | `whale_detector.py:1014`, `:1029` |
| `updated_at` | момент последнего обновления записи | Both | `NOW()` hardcoded | `whale_detector.py:1017`, `:1030` |
| `source_new` | способ обнаружения кита системой | **INSERT only** | `'auto_detected'` hardcoded | `whale_detector.py:1017` |

### Что НЕ изменяется в `DO UPDATE SET`

- `source_new` — фиксируется только при первом INSERT. При повторном обнаружении значение сохраняется, что корректно: способ обнаружения кита не меняется.
- `copy_status` — **никогда** не трогается этим шагом. При INSERT принимает default из схемы whales ('none'). Допустимые значения: 'none' / 'tracked' / 'paper' / 'excluded' / 'live'. Меняется только оператором вручную или через governance-процедуру (WHALE_STATUS_TRANSITIONS.md), как правило на основе аналитики roundtrip'ов (P&L, win-rate, число завершённых позиций). Значение определяет, по какой ветке магистрали пойдут будущие сделки этого кита: 'none' → стандартный путь (запись в whale_trades, далее roundtrip-реконструкция); 'paper' → дополнительно активирует DB-trigger trigger_copy_whale_trade при INSERT в whale_trades, создающий запись в paper_trades; 'excluded' → шаг 2A полностью блокирует UPDATE для этого кита (защита WHERE whales.copy_status != 'excluded', whale_detector.py:1032).
- `tier` — не трогается шагом 2A. Управляется `WhalePoller` через UPDATE в targeted-циклах.
- `last_targeted_fetch_at` — не трогается шагом 2A. Управляется `WhalePoller`.

### Сценарий UPDATE для уже существующего кита

При повторном обнаружении кита (`wallet_address` уже есть в `whales`) шаг 2A выполняет следующее:

**Что обновляется** (13 из 14 колонок):
- **Метрики активности**: `total_trades`, `total_volume_usd`, `avg_trade_size_usd` — полностью перезаписываются на новые значения из текущего окна агрегации. Это **не инкрементальное** обновление — значения **заменяются** на пересчитанные из последних 500 сделок Polymarket.
- **Производные показатели**: `risk_score`, `qualification_status` — пересчитываются по текущим данным.
- **Счётчики окон**: `trades_last_3_days`, `trades_last_7_days`, `days_active_7d`, `days_active_30d` — обновляются по эвристическим формулам шага 2A (см. RED FLAG #6 в §13).
- **Имя кита**: `notes` — перезаписывается из `whale.name` (если изменилось в API).
- **Timestamps**: `last_active_at`, `updated_at` — устанавливаются в `NOW()`.

**Что сохраняется без изменений** (governance-поля, не во владении шага 2A):
- `source_new` — остаётся `'auto_detected'` (или любое другое значение, проставленное при первой регистрации), потому что не входит в `DO UPDATE SET`.
- `copy_status` — `'none'` / `'paper'` / `'tracked'` / `'live'` / `'excluded'` — управляется операторами и отдельной governance-логикой.
- `tier` — `'HOT'` / `'WARM'` / NULL — управляется `WhalePoller`.
- `last_targeted_fetch_at` — управляется `WhalePoller`.
- `id` — PK, не трогается.

**Когда UPDATE блокируется полностью:**
Условие `WHERE whales.copy_status != 'excluded'` (`whale_detector.py:1032`) гарантирует, что для китов, помеченных оператором как `excluded`, UPDATE **не применяется вообще** — ни одна из 13 колонок не меняется, строка остаётся в БД ровно в том виде, в каком оператор её зафиксировал. При этом сама команда выполняется без ошибки (просто 0 строк затронуто), цикл продолжает работу со следующим адресом. RED FLAG #5 в §13: лог при этом всё равно записывается как `whale_updated`, хотя фактического UPDATE не произошло.

**Идемпотентность UPDATE:**
Если кит появился в двух последовательных итерациях `_polymarket_poll_loop` (через 60s) и его активность за это время не изменилась, второй UPDATE приведёт к тому же содержимому строки (за исключением `updated_at` и `last_active_at`, которые будут пересдвинуты на `NOW()`). Дополнительной нагрузки на downstream-консьюмеров это не создаёт — материализованные view (`whale_pnl_summary`, `paper_portfolio_state`) обновляются по своему расписанию, а не на каждый UPDATE строки `whales`.

### Idempotency

Полная на уровне таблицы: при повторных вызовах с тем же `wallet_address` строка обновляется in-place. Количество строк в `whales` равно количеству уникальных адресов, прошедших gate. Подробный сценарий повторного обновления — см. «Сценарий UPDATE для уже существующего кита» выше.

### Constraints / FK / индексы

- PK по `wallet_address`
- UNIQUE constraint обеспечивает ON CONFLICT
- FK из `whale_trades.whale_id → whales.id` существует (по знанию из шага 2B); шаг 2A создаёт целевую запись для этой FK

---

## 10. Условия успеха / частичного успеха / неуспеха

**Успех (на уровне одного кита):**
- INSERT прошёл (новый кит, его не было в `whales`)
- UPDATE прошёл (известный кит, `copy_status != 'excluded'`)
- В обоих случаях `session.commit()` отработал, лог `polymarket_new_whale` или `whale_updated`.

**Частичный успех (на уровне итерации):**
- Часть китов записана, часть нет. Каждый кит обрабатывается в собственном теле цикла; ошибка на одном ките не прерывает цикл — переход к следующему. На `whale_detector.py:1648`: `except Exception as e: logger.error("polymarket_fetch_failed", error=str(e))` ловит исключения целой итерации, не блокирует следующий tick цикла.

**Неуспех (на уровне одного кита):**
- SQL-ошибка в `session.execute()` → `session.rollback()` (в knowledge подтверждается стандартный паттерн `_save_whale_to_db()`); кит не записан, лог `save_whale_db_failed`, исключение не пробрасывается.
- Поглощённая ошибка: вызывающий код **не знает** о неуспехе записи. RED FLAG #8 в §13.

**Неуспех (на уровне итерации):**
- Сбой `_ensure_database()` или SQLAlchemy session factory — все киты итерации не записываются. Следующая итерация через 60s пытается заново.

---

## 11. Зависимости

### Upstream

- **Шаг 1** — поставляет `List[TradeWithAddress]` в `_polymarket_poll_loop`. Без шага 1 шаг 2A не получает данных.

### Downstream consumers таблицы `whales`

Все 4 targeted-цикла **читают** `whales` и зависят от того, что шаг 2A заполнил её:

| Цикл | Тип чтения | Колонки SELECT | Файл:строка |
|------|-----------|----------------|-------------|
| `_paper_poll_loop` | SELECT only | `wallet_address WHERE copy_status='paper'` | `whale_detector.py:1653–1656` |
| `_tracked_poll_loop` | SELECT only | `wallet_address WHERE copy_status='tracked'` | `whale_detector.py:1787–1790` |
| `WhalePoller.run_hot_polling` | SELECT + UPDATE side-effect | `id, wallet_address, tier, ...` | `whale_poller.py:128–139`, `:328–342` |
| `WhalePoller.run_warm_polling` | SELECT + UPDATE side-effect | то же | `whale_poller.py:128–139` |

**Важно:** targeted-циклы не вызывают `_save_whale_to_db()`. Они полагаются на discovery-цикл как единственный источник регистрации.

### External services

Нет. Шаг 2A работает только с локальной БД и in-memory структурами процесса.

### Параллельная ветвь (не зависимость, а параллелизм)

- **Шаг 2B** (запись сделок в `whale_trades`) выполняется в той же итерации `_fetch_polymarket_whales()`, но не передаёт данных в шаг 2A и не получает от него. Связь только через состояние БД между итерациями.

---

## 12. Наблюдаемость

### Логи

| Событие | Уровень | Контекст | Файл:строка |
|---------|---------|----------|-------------|
| `save_whale_to_db` | INFO | address[:10], total_trades, status | `whale_detector.py:990–994` (вход в метод) |
| `save_whale_db_no_session` | WARNING | address[:10] | `whale_detector.py:984–986` |
| `polymarket_new_whale` | INFO | address[:10], total_trades, volume_usd | `whale_detector.py:1593–1598` |
| `whale_updated` | INFO | address[:10], total_trades, volume_usd | `whale_detector.py:1600–1604` |
| `polymarket_whale_callback_failed` | ERROR | error | `whale_detector.py:1618–1620` |
| `polymarket_fetch_complete` | INFO | new_whales, total_traders | `whale_detector.py:1623–1628` |
| `polymarket_fetch_failed` | ERROR | error (вся итерация) | `whale_detector.py:1648` |

### Метрики

Не обнаружены. RED FLAG #9 в §13.

### Алерты

Алертов на состояние шага 2A не обнаружено. `pipeline_monitor` (cron каждые 30 минут, по PROJECT_STATE) контролирует общее состояние pipeline, но конкретно «регистрация китов остановилась» — не алертится.

### Что наблюдатель НЕ видит

- Молчаливые failure'ы `_save_whale_to_db()`: при ошибке execute() rollback'ится, лог ERROR, исключение не пробрасывается. Цикл продолжается без признаков проблемы для оператора.
- Адреса в логах редактированы (truncate `[:10]`), что усложняет ручной поиск конкретного кита.

---

## 13. Особые случаи и риски (RED FLAGs)

**RED FLAG #1 — Двойной gate `min_trades_for_quality`.**
Одна и та же проверка `stats.total_trades >= min_trades_for_quality` выполняется дважды: на `whale_detector.py:1509` (early-skip `continue`) и на `whale_detector.py:1586` (вход в блок регистрации). Между ними `stats` не модифицируется. Либо рудимент рефакторинга, либо страховка от мутации, не документировано. Поведенческого эффекта нет, но создаёт дополнительную точку для регрессий при изменении порога.

**RED FLAG #2 — `risk_score` рассчитывается через deprecated `win_rate=0`.**
В `DetectedWhale` (`whale_detector.py:158`) поле `win_rate` помечено DEPRECATED и инициализируется как `Decimal("0")` всегда. Функция `calculate_risk_score(...)` (`whale_detector.py:1568–1574`) использует это значение в формуле. Следствие: колонка `risk_score` в `whales` рассчитывается на основе константного нуля для win_rate. Реальная корреляция между профилем кита и записанным `risk_score` нарушена. Требует отдельной верификации логики `calculate_risk_score` — не входит в скоуп шага 2A.

**RED FLAG #3 — Dead computation `qualification_path`.**
На `whale_detector.py:1577–1584` вызывается `_calculate_qualification_path(...)`, результат присваивается полю `whale.qualification_path`. Однако в словаре параметров `_save_whale_to_db()` (`whale_detector.py:1034–1048`) ключа `qualification_path` нет. В SQL (`:1005–1033`) — тоже нет. Колонка удалена в ARC-501 (`whale_detector.py:1003`). Расчёт выполняется в каждой итерации, результат отбрасывается.

**RED FLAG #4 — Ветви 2A и 2B параллельны, кит регистрируется ПОСЛЕ записи его сделок.**
В `_fetch_polymarket_whales()` сначала выполняется пер-сделочный цикл шага 2B (`whale_detector.py:1462–1489`), записывающий сделки в `whale_trades`, затем пер-адресный цикл шага 2A (`whale_detector.py:1501–1620`), регистрирующий кита в `whales`. Для **впервые встреченного** кита это означает: его сделки попадают в `whale_trades` **до** того, как он зарегистрирован в `whales`. Последствия для `_lookup_whale_id` (используется на стороне шага 2B) — открытый вопрос до сборки шага 2B. Возможные сценарии: (а) `whale_id` = NULL для таких сделок; (б) lookup не находит кита и сделка теряется; (в) FK-constraint вызывает ошибку. Точное поведение требует верификации в шаге 2B.

**RED FLAG #5 — `_known_whales` загружается только для трёх статусов.**
На `whale_detector.py:402–408` запрос загружает `WHERE qualification_status IN ('qualified', 'ranked', 'tracked')`. Киты со статусами `none`, `paper`, `excluded`, `live` (если такой используется) в set **не попадают**. Следствия:
- После рестарта контейнера первое обнаружение `paper`-кита залогируется как `polymarket_new_whale` (хотя кит уже в БД и используется в production).
- `excluded`-киты не в set: при их обнаружении срабатывает попытка UPDATE, но защита `WHERE copy_status != 'excluded'` блокирует изменение строки. Лог при этом всё равно пишется как `whale_updated`, что вводит в заблуждение.
Не баг записи данных, но дезориентирующая метрика «new vs updated».

**RED FLAG #6 — Эвристические формулы расчёта активности.**
Поля `trades_last_3_days = min(stats.total_trades, 10)` и `trades_last_7_days = min(stats.total_trades, 20)` (`whale_detector.py:1531`, `:1541`) — это **не подсчёт по фактическим timestamps сделок**, а грубые верхние оценки на основе общего числа сделок и одного timestamp `last_seen`. Формула систематически занижает реальную активность. Для китов с высокой плотностью сделок (10+ в день) `trades_last_3_days` всегда останется 10. Downstream-логика тиринга (HOT/WARM) использует эти поля — что может приводить к некорректной классификации.
**Примечание:** фоновая задача `update_whale_activity_counters` (`whale_detector.py`, hourly) пересчитывает эти счётчики из таблицы `whale_trades`. То есть значения, записанные шагом 2A, **через ≤1 час будут перезаписаны** на корректные. Но в окне до пересчёта downstream-логика видит занижённые цифры.

**RED FLAG #7 — Callback `on_whale_detected` — DORMANT в production.**
Механизм существует: атрибут `on_whale_detected` в `WhaleDetector.__init__` (`whale_detector.py:211`), вызовы в `process_trade()` (`:560–564`) и `_fetch_polymarket_whales()` (`:1614–1620`). Но в активном entry point `run_whale_detection.py:189–194` callback **не передаётся**. Код выполняется в каждой итерации (проверка `if self.on_whale_detected:`), но всегда пропускает блок. Классификация: SCRIPT-ONLY / DORMANT.

**RED FLAG #8 — Молчаливое поглощение ошибок записи.**
`_save_whale_to_db()` обрабатывает исключения внутри (rollback + лог ERROR), не пробрасывает наружу и не возвращает индикатор успеха (`-> None`). Вызывающий код в `_fetch_polymarket_whales()` не знает, записан кит или нет. Метрика «сколько китов записано в итерацию» в логе `polymarket_fetch_complete` (`new_whales`) опирается на счётчик `is_known`, инкрементируемый **до** попытки записи в БД. Возможна ситуация: лог говорит «записано N новых китов», а в БД на самом деле меньше.

**RED FLAG #9 — Нет метрик и алертов.**
Структурированные логи есть, но Prometheus/Statsd-метрики отсутствуют. Алерты на «регистрация китов остановилась N минут» не настроены. Внешний наблюдатель (Grafana / pipeline_monitor) не получит сигнал о деградации шага 2A до тех пор, пока downstream-эффект (отсутствие новых китов с `copy_status='paper'` или старение данных) не станет заметен — это часы или дни запаздывания.

**RED FLAG #10 — `notes` дублирует `whale.name` без контроля длины.**
Поле `notes` — единственный способ сохранить human-readable имя кита в `whales`. Записывается как `whale.name if whale.name else None` (`whale_detector.py:1047`). Имя из API не валидируется на длину; SQL-схема `whales.notes` может иметь ограничение (нужно проверить через `init_db.sql`). При длинном имени потенциально возможен truncate или ошибка вставки. Шаг 2A не имеет защиты.

---

## 14. Результат шага

После успешного выполнения для одного кита:

- В таблице `whales` существует строка с его `wallet_address` (новая после INSERT или обновлённая после UPDATE).
- Заполнены 14 колонок: 11 параметризованных + 3 hardcoded (`source_new`, `last_active_at`, `updated_at`). Полный список — §9.
- При INSERT: `source_new = 'auto_detected'`; `copy_status` принимает default из схемы (вероятно `'none'`, требует проверки через `init_db.sql`); `tier` остаётся NULL до первого обновления `WhalePoller`.
- Для нового кита copy_status = 'none' означает, что его сделки идут по стандартной ветке магистрали (запись в whale_trades → отложенная reconstruction в whale_trade_roundtrips). Paper-ветка магистрали (DB-trigger trigger_copy_whale_trade → paper_trades) активируется только после ручного изменения copy_status на 'paper', выполняемого оператором на основе аналитики roundtrip-метрик кита.
- При UPDATE: `source_new` не меняется; `copy_status` не меняется; `tier` не меняется. Меняются только метрики и timestamps.
- In-memory кэш `_known_whales` дополняется адресом (для новых).
- В логи попадает событие `polymarket_new_whale` или `whale_updated`.

После успешного выполнения для всей итерации:

- Каталог китов `whales` синхронизирован с фактическими адресами, обнаруженными в текущем 60-секундном окне Polymarket.
- Адреса с `< min_trades_for_quality` сделок **не попадают** в `whales` (но их сделки могли попасть в `whale_trades` через ветвь 2B — см. RED FLAG #4).
- Известные киты получили обновлённые `total_trades`, `total_volume_usd`, `last_active_at`, `trades_last_3_days/7_days`, `days_active_7d/30d` (но см. RED FLAG #6 — корректные значения активности придут через фоновую задачу).

**Состояние сделки** (в терминах магистрали): шаг 2A не меняет состояние конкретной сделки. Он меняет состояние **кита**, что является контекстом для downstream-логики (копи-торговля, тиринг, аналитика). Финальное состояние сделки определяется веткой 2B.

**Связь с шагом 2B и далее:**
- Кит, зарегистрированный в итерации N через 2A, имеет `whale_id` в БД к итерации N+1 → его сделки в `whale_trades`, записанные в N+1 через 2B, могут получить корректный FK через `_lookup_whale_id`.
- Кит со статусом `copy_status = 'paper'` (присваивается отдельным процессом, **не** шагом 2A) активирует DB-trigger `trigger_copy_whale_trade` на каждом INSERT в `whale_trades` → создаётся paper-trade. Это уже следующий шаг магистрали (предположительно шаг 3, верификация после сборки 2B).

---

## 15. Краткая бизнес-формула шага

```
ВХОД: trades: List[TradeWithAddress]  (из шага 1, каждые 60s)

  │
  ├── aggregate_by_address(trades)
  │   └── Dict[address → AggregatedTraderStats]
  │       (без фильтрации: все адреса попадают в результат)
  │
  └── for (address, stats) in aggregated:
        │
        ├── GATE: stats.total_trades >= min_trades_for_quality (=10)?
        │   └── НЕТ → continue (кит не регистрируется)
        │       (его сделки уже могли быть записаны веткой 2B — см. RED FLAG #4)
        │
        ├── is_known = address in _known_whales (in-memory Set)
        ├── compute: trades_last_3d/7d, days_active_7d/30d (эвристика — RED FLAG #6)
        ├── compute: risk_score (через deprecated win_rate=0 — RED FLAG #2)
        ├── compute: qualification_path (НЕ записывается — RED FLAG #3)
        │
        ├── _save_whale_to_db(whale):
        │   └── INSERT INTO whales (...11 параметров...) VALUES (...)
        │       ON CONFLICT (wallet_address) DO UPDATE SET ...
        │       WHERE whales.copy_status != 'excluded'  (защита от перезаписи)
        │       └── session.commit()
        │
        ├── if not is_known: _known_whales.add(address) + log new_whale
        │   else: log whale_updated
        │
        └── on_whale_detected(whale)  — DORMANT в production (RED FLAG #7)

ВЫХОД:
  - таблица whales: строка существует и актуальна для каждого кита,
    прошедшего gate (>=10 сделок в окне)
  - in-memory _known_whales дополнен новыми адресами
  - downstream targeted-циклы (paper/tracked/HOT/WARM) могут читать
    этих китов из whales для пер-кошельковой работы
```