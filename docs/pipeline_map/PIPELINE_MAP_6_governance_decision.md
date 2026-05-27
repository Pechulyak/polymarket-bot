# ШАГ 6. GOVERNANCE-РЕШЕНИЕ: MANUAL UPDATE `whales.copy_status`

## Краткая характеристика (TL;DR)

Шаг 6 — **manual gate** governance-контура, единственная точка во всей системе, где значение `whales.copy_status` действительно изменяется. Никаких triggers на таблице `whales`, никаких автоматических процессов, никаких cron-задач, способных изменить `copy_status` — UPDATE выполняется по решению владельца проекта, раз в неделю.

### Шаг 6 в бизнес-нотации

Workflow шага 6 распределён между тремя акторами:

1. **Владелец проекта** запускает Manual SQL (шаг 5) в DBeaver и пересылает результаты `whale_audit.sql` / `whale_status.sql` в чат аналитики вместе с Telegram-сводкой Weekly AI.
2. **Чат аналитики** на основании этих данных формирует **список китов на повышение / понижение** с обоснованием по каждой позиции (тип перехода, причина, расчёт `estimated_capital` для `→ paper`, `exclusion_reason` для `→ excluded`).
3. **Владелец проекта** проверяет список, согласовывает изменения и **передаёт задачу Roo** на выполнение конкретных UPDATE-statement-ов.
4. **Roo** выполняет UPDATE-ы в БД по правилам `WHALE_STATUS_TRANSITIONS.md v1.1` §3.

Пять канонических переходов (определены в `WHALE_STATUS_TRANSITIONS.md v1.1` §3):

1. **`none → tracked`** — кит из необработанных переводится в наблюдение (polling каждые 5 мин, но без paper-сделок).
2. **`tracked → paper`** — кит подтверждён как edge-source, начинает копироваться в paper. Обязателен расчёт `estimated_capital` и mandatory `whale_status.sql` для верификации (см. §11.2 спецификации).
3. **`paper → tracked`** — пауза копирования (downgrade), `estimated_capital` сохраняется для возможного recovery.
4. **`any → excluded`** — исключение с обязательным `exclusion_reason` (одно из: `negative_pnl`, `auto_market_maker`, `edge_degraded`, `manual`).
5. **`excluded → tracked/paper`** — recovery, требует явного review и пересчёта `estimated_capital` при возврате в paper.

Каждый UPDATE — атомарная транзакция в одной SQL-команде. Накладных процедур, multi-statement workflows, validation-гейтов в БД нет. Корректность шага полностью лежит на дисциплине владельца проекта и качестве предложений чата аналитики; БД не валидирует, выполнил ли исполнитель предусмотренные spec'ом pre-actions (расчёт `estimated_capital`, mandatory `whale_status.sql`, проверка открытых paper-позиций).

---

## 1. Назначение шага

Шаг переводит **рекомендации шага 5 в фактическое состояние системы**. До шага 6 рекомендации существуют только как:
- Telegram-сообщение от Weekly AI (`recommendations_json` в `whale_ai_analysis`)
- Отчёт `whale_audit.sql` в DBeaver-сессии владельца проекта
- Отчёт `whale_status.sql` по конкретным китам
- Daily Alert-сообщения за последнюю неделю
- План UPDATE-ов «в голове владельца проекта»

После шага 6 рекомендации **материализованы в `whales.copy_status`** — что мгновенно меняет поведение нижестоящих процессов:
- `trigger_copy_whale_trade` начинает (или прекращает) создавать paper-сделки для этого кита.
- Discovery-пайплайн (`whale_detector`, `whale_tracker`) перестаёт обновлять метрики этого кита, если он переведён в `excluded` — защита, чтобы автоматическое обнаружение не «откатило» решение о исключении.
- Polling-циклы в `whale_detector` начинают (или прекращают) опрашивать кита.

Бизнес-смысл: «чат аналитики предложил → владелец проекта согласовал → Roo выполнил одну SQL-команду → операционный режим кита изменился».

---

## 2. Статус

**MANUAL-ACTIVE.** Шаг выполняется регулярно (еженедельно) в production. Никакой docker- или cron-обёртки нет — это SQL-команды, выполняемые владельцем проекта в DBeaver-сессии.

Дата верификации: 2026-05-26.

**Не модифицируется** ни одним автоматическим процессом — verified through full code audit (Roo: «В коде и SQL отсутствуют триггеры на таблице whales, автоматические UPDATE-statement-ы, меняющие copy_status, функции, изменяющие copy_status, cron-задачи, изменяющие copy_status»).

---

## 3. Исходные файлы

### Authoritative source правил

- `docs/WHALE_STATUS_TRANSITIONS.md v1.1` — единственный источник правил перехода. Содержит SQL-шаблоны для всех 5 переходов (§3.1–§3.5), checklists pre-actions (§11.1–§11.3), формулу `estimated_capital` (§12.3), инварианты (§5), запрещённые переходы (§4).

### SQL-команды

UPDATE-statement-ы шага 6 — это **inline SQL**, выполняемый владельцем проекта напрямую в DBeaver. Не существует отдельного файла типа `scripts/promote_whale.sql` или функции `promote_whale_to_paper(wallet)`. Каждый UPDATE — копи-паст из:
- Telegram-рекомендации Weekly AI (`scripts/run_weekly_whale_analysis.py:519-539` генерирует готовые SQL-команды)
- SQL-шаблонов в `WHALE_STATUS_TRANSITIONS.md` §3

### Целевая таблица

- `whales` — DDL в `scripts/init_db.sql:200-340` (раздел `CREATE TABLE whales`). Релевантные для шага 6 колонки: `copy_status`, `reviewed_at`, `updated_at`, `whale_comment`, `estimated_capital`, `capital_estimation_method`, `exclusion_reason`. Подробнее в §9.

### Защита решений по `excluded`-китам от автоматической перезаписи

Discovery- и tracker-пайплайны при повторном обнаружении уже известного кита делают `INSERT ... ON CONFLICT DO UPDATE` на строке `whales`. Если бы такая перезапись срабатывала на excluded-китах, она могла бы случайно изменить их operator-managed поля. Защита реализована добавлением фильтра `WHERE whales.copy_status != 'excluded'` к `ON CONFLICT`-клаузам — для excluded-китов автоматическая перезапись просто пропускается:

- `src/research/whale_detector.py:1032` — в `_save_whale_to_db()`.
- `src/research/whale_tracker.py:594` — в `save_whale()`.

Других защит нет (для `paper` и `tracked` подобный фильтр отсутствует — см. §13 RF2).

---

## 4. Контейнер

**Машина владельца проекта с установленным DBeaver-клиентом.** Подключение к `polymarket_postgres` через service-аккаунт БД. **Не входит в production-инфраструктуру**: не виден в `docker ps`, не покрыт healthcheck, нет supervisor, нет audit-логов на уровне самого DBeaver.

Контейнер `bot`, `whale-detector`, `roundtrip_builder` шаг 6 не выполняют. Шаг 6 — это исключительно SQL-команды, посылаемые в Postgres напрямую через клиент.

---

## 5. Триггер запуска и расписание

**Триггер:** владелец проекта в воскресенье открывает DBeaver-сессию (продолжение шага 5), просматривает план UPDATE-ов и поочерёдно выполняет SQL-команды для каждого кита в плане.

**Расписание:** еженедельное, привязано к ритму шага 5. Ad-hoc запуски возможны (например, при критическом Daily Alert в середине недели), но не предписаны процессом. Master подтвердил: «все изменения китов делаю раз в неделю» — это рабочий ритм, не формальное ограничение.

**Не зарегистрировано в системе:** нет crontab, нет supervisor, нет docker. Никаких уведомлений о пропуске недели. Воспроизводимость гарантируется ритуалом владельца проекта.

---

## 6. Алгоритм шага

Шаг состоит из **последовательности SQL-команд**, одна на одного кита, по правилам `WHALE_STATUS_TRANSITIONS.md` §3. Каждая команда выполняется независимо от других — нет общей транзакции на batch.

### Общий алгоритм workflow

1. Владелец проекта получил отчёты шага 5 (Weekly AI Telegram, whale_audit-вывод в DBeaver, whale_status-выводы по кандидатам) и переслал результаты в чат аналитики.
2. Чат аналитики формирует **план UPDATE-ов**: список пар `(wallet_address, target_copy_status)` с обоснованиями (тип перехода, причина, `estimated_capital` для `→ paper`, `exclusion_reason` для `→ excluded`).
3. Для каждой пары — чат аналитики определяет тип перехода (один из 5 канонических).
4. Чат аналитики выполняет **pre-actions** перехода по `WHALE_STATUS_TRANSITIONS.md` §11.1–§11.3 (см. ниже): расчёт `estimated_capital`, проверка mandatory `whale_status.sql`-данных, проверка открытых paper-позиций.
5. Чат аналитики компонует готовые SQL-команды UPDATE и представляет план владельцу проекта на согласование.
6. После согласования владельцем проекта — задача передаётся Roo, который выполняет UPDATE-ы в БД. Проверка «rows affected = 1» — на стороне Roo.
7. Факт изменения фиксируется в `whale_comment` (накопительная конкатенация) и `reviewed_at`. Отдельного audit-log в БД нет.

### Pre-actions по типу перехода

Это **краткая выжимка** из `WHALE_STATUS_TRANSITIONS.md` §11 — полный текст в первоисточнике.

**Для `none → tracked` и `excluded → tracked`** (§11.1):
- Tier refresh через `_update_whale_activity` (запускается отдельно перед UPDATE), проверка `tier ∈ {HOT, WARM}` на момент UPDATE.
- Лог причины в `whale_comment`.

**Для `tracked → paper` и `excluded → paper`** (§11.2):
- Всё из §11.1.
- **Mandatory** запуск `whale_status.sql` владельцем проекта (см. шаг 5) — при расхождении с audit-отчётами >5pp WR или >10% PnL результаты `whale_status.sql` authoritative.
- Post-reset adequacy check: `roundtrips_closed_post_reset ≥ 10`, `post_reset_wr ≥ 60%` (читается из §300 post-reset блока вывода `whale_status.sql`).
- Расчёт `estimated_capital` чатом аналитики по одному из четырёх методов (см. §7) — обычно `max_daily_volume_30d`.

**Для `any → excluded`** (§11.3):
- Заполнить `exclusion_reason`: одно из `negative_pnl`, `auto_market_maker`, `edge_degraded`, `manual`.
- Проверить открытые paper-позиции кита — они **не закрываются автоматически**, доигрываются через materialized views (см. §13 RF5).

**Для `paper → tracked`** (§3.3):
- `estimated_capital` **не очищается** — сохраняется для возможного recovery.

**Для `excluded → tracked/paper`** (§3.5):
- Очистка `exclusion_reason = NULL`.
- При recovery в `paper` — **заново рассчитать** `estimated_capital`, не использовать сохранённое значение.

### Запрещённые переходы

По `WHALE_STATUS_TRANSITIONS.md` §4: `tracked → none`, `paper → none`, `excluded → none` — не поддерживаются. Прямой `none → paper` без промежуточного `tracked` — discouraged, но технически возможен (БД примет UPDATE). Запретов на уровне CHECK constraints нет — соблюдение лежит на дисциплине чата аналитики и контроле владельца проекта.

---

## 7. Формат входных данных

### Решение, принятое владельцем проекта (на основе предложения чата аналитики)

- **`wallet_address`** — какого кита переводим (lower-case hex, валидация в момент компоновки SQL).
- **`target_copy_status`** — куда переводим (одно из `none`, `tracked`, `paper`, `excluded`; `live` — outside scope текущего документа, см. §13 RF10).
- **`exclusion_reason`** — только для перехода в `excluded`. Допустимые значения: `negative_pnl`, `auto_market_maker`, `edge_degraded`, `manual`.
- **`whale_comment`** — текст обоснования. Накапливается через `whale_comment = COALESCE(whale_comment, '') || '<action>'` — не перезаписывается, а добавляется к существующему значению.

### Расчётные параметры (для перехода в `paper`)

- **`estimated_capital`** — численное значение в USD. Рассчитывается чатом аналитики **до** компоновки UPDATE по одному из четырёх методов:

  | `capital_estimation_method` | Формула | Когда использовать |
  |---|---|---|
  | `max_daily_volume_30d` | `MAX(SUM(size_usd)) GROUP BY DATE(traded_at)` за 30 дней | основной метод по умолчанию для китов с историей ≥30 дней |
  | `p99_trade_20x` | `PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY size_usd) × 20` | fallback для китов с <30 дней истории |
  | `peak_exposure_2x` | `MAX(одновременная открытая экспозиция) × 2` | для китов с >100 roundtrips |
  | `manual` | произвольное значение, заданное владельцем проекта | override-режим при недоверии автоматическим расчётам |

  Метод записывается в колонку `capital_estimation_method`, само значение — в `estimated_capital`.

### Источники обоснования (read-only входные данные для чата аналитики)

- Telegram-рекомендация Weekly AI (`recommendations_json` шага 5).
- Daily Alert-сообщения за неделю.
- Вывод `whale_audit.sql` из DBeaver-сессии владельца проекта (фильтр `WHERE copy_status IN ('none', 'tracked')` — показывает кандидатов на promotion, не paper/excluded — см. §13 RF8).
- Вывод `whale_status.sql` по конкретному киту (mandatory для `→ paper`).

---

## 8. Формат выходных данных

### Каждый UPDATE-statement

Возвращает только `rows affected` (обычно `1`, при ошибке wallet_address — `0`). Не возвращает старое значение `copy_status`, не возвращает diff, не пишет в audit-log. Если Roo / владелец проекта хочет увидеть результат — следующая SQL-команда:

```
SELECT wallet_address, copy_status, reviewed_at, whale_comment
FROM whales WHERE wallet_address = '<addr>';
```

### Косвенный выход — изменения в downstream

После коммита UPDATE-а:
- Следующий INSERT в `whale_trades` для этого кита через DB-trigger `trigger_copy_whale_trade` будет читать **новое** значение `copy_status` (synchronous, no caching).
- Следующая итерация `_fetch_paper_whale_trades()` / `_fetch_tracked_whale_trades()` в `whale_detector` будет читать **новое** значение (no caching).
- Materialized views `whale_pnl_summary` и др. увидят изменение только при следующем refresh (`15 */2 * * *`).

Записи в `paper_trades`, `paper_trade_notifications`, `whale_trade_roundtrips` — **не модифицируются** этим шагом. Уже существующие открытые paper-позиции после `→ excluded` продолжают существовать (см. §13 RF5).

---

## 9. Записи в БД

Шаг 6 пишет **в одну таблицу** — `whales` — и только тех колонок, которые указаны в `WHALE_STATUS_TRANSITIONS.md` §3 для соответствующего перехода.

### Полный набор колонок, изменяемых на шаге 6

| Колонка | Тип | Бизнес-смысл | Когда меняется |
|---|---|---|---|
| `copy_status` | VARCHAR(10) | основной governance-статус кита | во всех 5 переходах |
| `reviewed_at` | TIMESTAMP | время принятия governance-решения | во всех 5 переходах |
| `updated_at` | TIMESTAMP | время последнего изменения строки | во всех 5 переходах (плюс автоматически другими процессами) |
| `whale_comment` | TEXT | rationale решения, накапливается через конкатенацию | во всех 5 переходах |
| `estimated_capital` | DECIMAL(20,8) | капитал кита для Kelly sizing | только в `→ paper` (tracked→paper и excluded→paper) |
| `capital_estimation_method` | VARCHAR(20) | метод расчёта `estimated_capital` | только в `→ paper` |
| `exclusion_reason` | VARCHAR(50) | причина исключения | в `→ excluded` (SET) и `excluded → recovery` (SET NULL) |

### Колонки `whales`, **не** изменяемые шагом 6

- `whale_category` — заполняется `category_backfill.py`, не относится к governance-контуру.
- `notes` — произвольные заметки, не упоминаются в `WHALE_STATUS_TRANSITIONS.md`.
- `qualification_status` — управляется автоматически discovery-пайплайном (`discovered/candidate/tracked/qualified/ranked/cold`).
- `tier` — управляется `_update_whale_activity` (HOT/WARM/COLD).
- Все activity-метрики (`total_trades`, `total_volume_usd`, `last_active_at`, и др.) — discovery и polling.
- Все P&L-агрегаты (`total_pnl_usd`, `win_rate_confirmed`, `total_roundtrips`, и др.) — шаг 4 магистрали.

### Constraint-валидация на уровне БД

- `copy_status`: CHECK `IN ('none', 'paper', 'live', 'tracked', 'excluded')`. БД отвергнет UPDATE с любым другим значением.
- Колонка **nullable**, без NOT NULL — теоретически возможен UPDATE в `NULL` (см. §13 RF6).
- Остальные governance-колонки — без CHECK constraints. БД примет любой непустой `exclusion_reason`, любую строку в `capital_estimation_method`, любое значение `estimated_capital`. Дисциплина соблюдения spec'а — на чате аналитики и владельце проекта.

---

## 10. Условия успеха / частичного успеха / неуспеха

### Per-UPDATE

| Исход | Условие | Поведение |
|---|---|---|
| Успех | `rows affected = 1`, ошибок нет | кит переведён, downstream-эффекты включаются с следующей операции |
| Wallet не найден | `rows affected = 0` | UPDATE отработал без ошибок, но ничего не изменил — Roo должен проверять (см. §13 RF1) |
| Невалидный `copy_status` | violation of CHECK constraint | БД отвергает UPDATE, ошибка возвращается Roo и эскалируется владельцу проекта |
| WHERE-условие не сработало | например, `excluded → paper` написан как `WHERE copy_status = 'tracked'` (ошибка в плане чата аналитики) | `rows affected = 0`, как «wallet не найден» |
| Конкуренция за строку | другой процесс держит row lock (например, idle UPDATE из polling) | UPDATE ждёт; обычно секунды; deadlock-ов в production не наблюдалось |

### Per-batch (вся еженедельная сессия)

- **Полный успех:** все UPDATE-ы из плана, согласованного владельцем проекта, отработали с `rows affected = 1`, обоснования записаны в `whale_comment`, для `→ paper` рассчитан `estimated_capital`.
- **Частичный успех:** часть UPDATE-ов выполнена, часть забыта/пропущена. БД этого не детектирует — нет понятия «план недели». Обнаруживается только при следующем еженедельном `whale_audit.sql`.
- **Полный провал:** владелец проекта пропустил неделю целиком. Никаких автоматических напоминаний — система продолжит работать на старом наборе paper-китов (см. §13 RF3).

---

## 11. Зависимости

### Upstream

- **Шаг 5** — поставляет всю информационную базу: Weekly AI Telegram-сообщение, `whale_audit.sql` вывод, `whale_status.sql` вывод. Без шага 5 решения шага 6 формально нарушают `WHALE_STATUS_TRANSITIONS.md` §11.2 (mandatory `whale_status.sql` перед `→ paper`).
- **Шаг 4** — поставляет агрегаты `whales.total_pnl_usd`, `win_rate_confirmed`, `total_roundtrips`, которые читаются шагом 5 как input. Опосредованно — основа для всех governance-решений.
- **`_update_whale_activity`** (отдельный процесс) — должен быть запущен **перед** UPDATE-ом перехода в `tracked` или `paper` (§11.1 pre-actions). Не входит в шаг 6 формально, но является обязательным prerequisite. Выполняется владельцем проекта или включается в задачу для Roo как pre-action.

### Downstream (косвенные эффекты UPDATE `copy_status`)

Никаких автоматических triggers на `whales`. Все downstream-эффекты — через **последующее чтение** `copy_status` другими процессами:

| Процесс | Файл / location | Фильтр | Что меняется при UPDATE `copy_status` |
|---|---|---|---|
| `trigger_copy_whale_trade` | `scripts/create_copy_trigger.sql:49` | `copy_status = 'paper'` | следующие INSERT в `whale_trades` начнут/прекратят создавать `paper_trades` |
| `_fetch_paper_whale_trades` | `src/research/whale_detector.py:1652` | `copy_status = 'paper'` | polling кита включается/выключается (paper-цикл, 30s) |
| `_fetch_tracked_whale_trades` | `src/research/whale_detector.py:1765` | `copy_status = 'tracked'` | polling кита включается/выключается (tracked-цикл, 300s) |
| `_save_whale_to_db` (защита excluded от перезаписи) | `src/research/whale_detector.py:1032` | `WHERE whales.copy_status != 'excluded'` | discovery перестаёт автоматически обновлять метрики excluded-кита |
| `save_whale` (защита excluded от перезаписи) | `src/research/whale_tracker.py:594` | `WHERE whales.copy_status != 'excluded'` | tracker перестаёт автоматически обновлять метрики excluded-кита |
| `run_daily_whale_alert.py` | various `check_*` | разные | Daily Alert начинает/прекращает учитывать кита |
| `whale_pnl_summary` materialized view | (определение в БД) | `copy_status IN ('paper', 'tracked', 'excluded')` | после next REFRESH (`15 */2 * * *`) кит включается/выключается |
| `paper_portfolio_state`, `paper_simulation_pnl` | (определение в БД) | через JOIN с `paper_trades` | косвенно зависят (paper_trades создаются только для `paper`) |

### External

- **DBeaver** (клиент владельца проекта) — путь выполнения SELECT-проверок и при необходимости manual UPDATE-ов; основной канал выполнения — Roo через service-аккаунт БД.
- **Postgres** — приём UPDATE-statement-ов от Roo / DBeaver, синхронная активация trigger-ов в той же транзакции.

Никаких HTTP-API, никаких Telegram-вызовов на самом шаге 6. Telegram использовался только на шаге 5 для доставки рекомендации владельцу проекта.

### Параллельные процессы (не блокирующие)

- **Materialized views refresh** (`15 */2 * * *`) — параллельно обновляет `whale_pnl_summary`, `paper_portfolio_state`, `paper_simulation_pnl`. UPDATE шага 6 не блокирует refresh, refresh не блокирует UPDATE.
- **Discovery / polling-циклы** `whale_detector` — могут параллельно UPDATE-ить ту же строку (метрики активности, `updated_at`). PostgreSQL row-level lock сериализует — Roo получит короткое ожидание, не deadlock. Фильтр `WHERE copy_status != 'excluded'` в `ON CONFLICT`-клаузе discovery работает атомарно — даже при гонке UPDATE шага 6 в `excluded` и одновременной автоматической перезаписи, перезапись пропускается, как только commit шага 6 виден.

---

## 12. Наблюдаемость

### Что фиксируется

- **`reviewed_at`** в строке `whales` — timestamp последнего governance-решения, записывается в момент выполнения UPDATE.
- **`whale_comment`** — текстовый лог последовательных решений (через `||=`-конкатенацию).
- **`updated_at`** — timestamp последней модификации строки (любой колонки, любым процессом).

### Что не фиксируется

- **История переходов** `copy_status`. Нет таблицы `governance_audit_log`, нет change data capture, нет partitioned snapshots. После UPDATE `paper → tracked` нельзя узнать из БД, что раньше было `paper` — кроме как через парсинг `whale_comment` (текст).
- **Идентификатор исполнителя.** БД не различает, кто выполнил UPDATE — владелец проекта вручную через DBeaver, Roo через service-аккаунт, или потенциальный будущий процесс. Все UPDATE-ы выглядят одинаково.
- **Связь с конкретной рекомендацией AI / предложением чата аналитики.** Нет FK на `whale_ai_analysis.id`, нет ссылки на сессию чата аналитики. В `whale_comment` владелец проекта / Roo могут (но не обязаны) упомянуть источник предложения.
- **Факт запуска `whale_status.sql`.** Mandatory pre-action перед `→ paper` не enforced — владелец проекта / чат аналитики могут пропустить, БД примет UPDATE.
- **Промежуточные расчёты `estimated_capital`.** Метод записывается (`capital_estimation_method`), но не исходные данные. Воспроизвести расчёт можно только повторным запуском соответствующего SQL.

### Метрики / алерты

Не экспортируются. Внешний наблюдатель может детектировать активность шага 6 только косвенно — например, через `SELECT COUNT(*) FROM whales WHERE reviewed_at > NOW() - INTERVAL '7 days'`. В Grafana / pipeline_monitor таких метрик нет.

---

## 13. Особые случаи и риски (RED FLAGs)

**RF1 [process — материализован] — `rows affected = 0` без явного сигнала.**
При опечатке в `wallet_address` или неверном WHERE-условии (например, `excluded → paper` через `WHERE copy_status = 'tracked'`) PostgreSQL не возвращает ошибку — просто `rows affected = 0`. Roo должен явно проверять rows affected после каждого UPDATE и эскалировать владельцу проекта несоответствие; владелец проекта в DBeaver может не заметить при batch-просмотре. Защита — после каждого UPDATE делать SELECT для проверки факта изменения, и встраивать эту проверку в задачу для Roo.

**RF2 [governance — материализован] — Защита от автоматической перезаписи существует только для `excluded`.**
Discovery / tracker имеют фильтр `WHERE copy_status != 'excluded'` в `ON CONFLICT`-клаузах — для `excluded`-китов автоматическая перезапись пропускается. Для `paper` и `tracked` такой защиты нет — это осознанное решение, основанное на том, что discovery никогда не пишет в `copy_status` (что подтверждено code audit'ом). Однако теоретически, если в будущем добавится процесс, делающий `ON CONFLICT DO UPDATE` на `whales`, он сможет случайно перезаписать paper-статус, если не сохранит фильтр. Латентный риск регрессии при добавлении новых пишущих процессов.

**RF3 [process — материализован] — Пропуск еженедельного окна.**
Если владелец проекта пропустил воскресенье, шаг 6 не выполняется до следующего воскресенья. Никаких напоминаний нет. Киты, заслуживающие excluded по WR-degradation (например, новый паттерн `auto_market_maker`), продолжают генерировать paper-сделки ещё неделю. Daily Alert частично компенсирует через `check_wr_degradation`, но реакция всё равно — только следующее окно. См. также RF5 шага 5.

**RF4 [data — материализован] — `whale_comment` как единственный quasi-audit-trail.**
`whale_comment = COALESCE(whale_comment, '') || '<action>'` — единственный способ восстановить историю решений. Текст накапливается без структуры, без разделителей, без timestamp-ов внутри. Через несколько лет работы поле может стать многокилобайтным, плохо парсится, теряет читаемость. Кандидат на введение отдельной структурированной таблицы `whales_status_history` (см. RF7).

**RF5 [governance — материализован] — Открытые paper-позиции после `→ excluded` не закрываются.**
По `WHALE_STATUS_TRANSITIONS.md` §3.4: «Проверить открытые paper-позиции (они не закрываются автоматически, досыгрываются до settlement)». Технически: `paper_trades.status` остаётся `'open'` навсегда (см. шаг P3 — нет процесса settlement для `paper_trades`); P&L материализуется через JOIN с roundtrip-ами кита в `paper_simulation_pnl` при следующем refresh views. Это **корректное** поведение, но: (a) чат аналитики и владелец проекта должны это понимать, (b) расчёт `our_pnl = whale_pnl × (kelly_size / whale_size)` после exclusion может удивлять — кит формально исключён, а P&L продолжает считаться. Защита — упоминание в `whale_comment` при `→ excluded` факта наличия открытых позиций; это pre-action чата аналитики.

**RF6 [data — латентный] — `copy_status` nullable.**
В DDL нет NOT NULL. Теоретически возможен UPDATE с `copy_status = NULL` (например, опечатка в SQL). Все downstream-фильтры используют `=` и `!=`, которые на NULL возвращают NULL (не FALSE) — то есть кит с `copy_status = NULL` молча выпадет из всех polling-циклов и trigger-фильтров, но останется в `whales` как «зомби». Защита — DEFAULT 'none' предотвращает это при INSERT, но не при злонамеренном/ошибочном UPDATE.

**RF7 [governance — latent / open issue] — `copy_status_updated_at` not implemented.**
По `WHALE_STATUS_TRANSITIONS.md` §13 «open question»: отдельная колонка `copy_status_updated_at` была proposed but not implemented (отдельный TRD-тикет). Без этой колонки timestamp последнего изменения именно `copy_status` неотличим от любого другого изменения строки (`updated_at` мигает при любом polling). Это ограничивает аналитику типа «как давно кит в paper».

**RF8 [governance — материализован] — `whale_audit.sql` фильтрует по `('none', 'tracked')`.**
Verified Roo: `scripts/whale_audit.sql:80` содержит `WHERE w.copy_status IN ('none', 'tracked')`. То есть отчёт показывает кандидатов на promotion, но **не показывает** paper-китов и excluded — для их анализа владелец проекта должен использовать `whale_status.sql` индивидуально или модифицировать `whale_audit.sql`. Это влияет на качество решений: при еженедельном обзоре `paper → tracked` или `paper → excluded` владелец проекта не получает агрегатного обзора всех paper-китов в одном экране. Защита — Weekly AI Telegram содержит per-paper recommendations, частично компенсирует.

**RF9 [governance — материализован] — Прямой `none → paper` discouraged but allowed.**
По `WHALE_STATUS_TRANSITIONS.md` §4: прямой переход `none → paper` без промежуточного `tracked` — discouraged. БД примет такой UPDATE (нет state-machine constraint). Опасность: пропускается period наблюдения через `tracked`, mandatory `whale_status.sql` всё равно требуется, но без накопленной истории polling-данных. Защита — дисциплина чата аналитики (не предлагать такой переход) и контроль владельца проекта на этапе согласования плана.

**RF10 [scope — out of scope] — `copy_status = 'live'` существует, но не описан здесь.**
CHECK constraint допускает значение `'live'` (real execution). На момент верификации `BuilderClient` DORMANT (sidebar 1C), процесса перехода `paper → live` не существует в production. Если в будущем `live` активируется — переход `paper → live` должен быть описан в `WHALE_STATUS_TRANSITIONS.md` §3.X (отдельный пункт spec'а) и здесь в §6 как 6-й тип перехода. Сейчас — out of scope.

---

## 14. Результат шага

После выполнения всех UPDATE-ов из плана еженедельного окна:

- В таблице `whales` обновлены `copy_status`, `reviewed_at`, `updated_at`, `whale_comment` (плюс `estimated_capital` / `capital_estimation_method` для `→ paper`, плюс `exclusion_reason` для `→ excluded` / NULL для recovery) — по одной строке на каждый принятый governance-решение.
- Все downstream-процессы видят новые значения с момента commit:
  - DB-trigger `trigger_copy_whale_trade` фильтрует по новому набору paper-китов
  - polling-циклы в `whale_detector` опрашивают новый набор tracked/paper-китов
  - discovery / tracker перестают автоматически обновлять метрики для нового набора excluded-китов (защита через `WHERE copy_status != 'excluded'`)
- Materialized views (`whale_pnl_summary`, `paper_portfolio_state`, `paper_simulation_pnl`) пока работают со старым набором — отрефрешатся на следующем `15 */2 * * *`.

**Состояние объекта магистрали** (кит как governance-сущность): governance-решение материализовано, кит начинает функционировать в новом операционном режиме. Это **завершение governance-цикла одной недели**; следующий цикл начнётся через 7 дней.

### Связь со следующим шагом магистрали

**Следующий шаг — никакой явной «следующий» магистрали в линейном смысле нет.** Шаг 6 — конец governance-полу-цикла. Дальше происходит **параллельная активность**:

- **Магистраль 1–4 первого потока** продолжает работать круглосуточно, реагируя на новый набор `copy_status` (через DB-trigger и polling).
- **Paper-ветка (P1–P4)** для китов, переведённых в `paper`, активируется при следующих BUY-сделках этих китов (P1 trigger, синхронно с шагом 2B), затем P2–P4 в течение часов/дней.
- **Через неделю** владелец проекта снова открывает governance-окно: шаг 5 (новая аналитика на основе изменённого состояния), затем шаг 6 (новый workflow: чат аналитики → согласование → Roo).

Это **циклическая структура** governance-контура. См. ASCII-схему §1 в `PIPELINE_MAP_INDEX.md` — цикл показан явно стрелкой «CYCLE: новые whale_trades → шаги 1-4 → новые агрегаты `whales` → новый шаг 5/6».

### Side-route: paper-ветка

Шаг 6 — точка, которая **включает или выключает** paper-ветку для конкретного кита (через изменение `copy_status` на `'paper'` или с `'paper'`). Сам шаг 6 не создаёт paper-сделок и не модифицирует существующие. Описание paper-ветки — шаги P1–P4 в `PIPELINE_MAP_INDEX.md` и отдельных документах P1/P2/P3/P4.

---

## 15. Краткая бизнес-формула шага

```
ВХОД: владелец проекта согласовал план, сформированный чатом аналитики на основе шага 5
      план UPDATE-ов: [(wallet_address, target_copy_status, reason), ...]
      Roo получил задачу на выполнение
  │
  │ для каждого пункта плана:
  ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │ определить тип перехода (один из 5 канонических)                 │
  └────┬─────────────────────────────────────────────────────────────┘
       │
       ├── none → tracked        (§3.1, §11.1 pre-actions)
       │   UPDATE whales SET copy_status='tracked',
       │      reviewed_at=NOW(), updated_at=NOW(),
       │      whale_comment=COALESCE(whale_comment,'')||'<reason>'
       │   WHERE wallet_address='<addr>' AND copy_status='none';
       │
       ├── tracked → paper       (§3.2, §11.1+§11.2 pre-actions,
       │                          mandatory whale_status.sql)
       │   расчёт estimated_capital (один из 4 методов)
       │   UPDATE whales SET copy_status='paper',
       │      estimated_capital=<value>,
       │      capital_estimation_method='<method>',
       │      reviewed_at=NOW(), updated_at=NOW(),
       │      whale_comment=COALESCE(...)||'<reason>'
       │   WHERE wallet_address='<addr>' AND copy_status='tracked';
       │
       ├── paper → tracked       (§3.3)
       │   UPDATE whales SET copy_status='tracked',
       │      reviewed_at=NOW(), updated_at=NOW(),
       │      whale_comment=COALESCE(...)||'<reason>'
       │   WHERE wallet_address='<addr>' AND copy_status='paper';
       │   -- estimated_capital сохраняется для возможного recovery
       │
       ├── any → excluded        (§3.4, §11.3 pre-actions)
       │   UPDATE whales SET copy_status='excluded',
       │      exclusion_reason='<reason_code>',
       │      reviewed_at=NOW(), updated_at=NOW(),
       │      whale_comment=COALESCE(...)||'<reason>'
       │   WHERE wallet_address='<addr>';
       │   -- открытые paper_trades НЕ закрываются (см. RF5)
       │
       └── excluded → tracked/paper (§3.5)
           UPDATE whales SET copy_status='<tracked|paper>',
              exclusion_reason=NULL,
              [estimated_capital=<new_value>,
               capital_estimation_method='<method>'  -- только для →paper]
              reviewed_at=NOW(), updated_at=NOW(),
              whale_comment=COALESCE(...)||'<reason>'
           WHERE wallet_address='<addr>' AND copy_status='excluded';
  │
  ▼
КОММИТ → DB-trigger trigger_copy_whale_trade сразу читает новое значение
       → polling-циклы при следующей итерации читают новое значение
       → защита `WHERE copy_status != 'excluded'` в discovery / tracker
         при следующих обнаружениях читает новое значение
       → materialized views — на следующем refresh (15 */2 * * *)
  │
  ▼
ВЫХОД: whales.copy_status в новом состоянии
       governance-цикл недели завершён
```

---

## 16. Ссылки на governance-spec

Authoritative source — `WHALE_STATUS_TRANSITIONS.md v1.1`. Кратко:

- **§3.1 `none → tracked`** — promotion в наблюдение.
- **§3.2 `tracked → paper`** — promotion в копирование, обязателен расчёт `estimated_capital` (методы — §12.3).
- **§3.3 `paper → tracked`** — downgrade, пауза копирования, `estimated_capital` сохраняется.
- **§3.4 `any → excluded`** — exclusion с обязательным `exclusion_reason`, открытые paper-позиции «доигрываются».
- **§3.5 `excluded → tracked/paper`** — recovery, требует явного review.
- **§4 Запрещённые переходы:** `tracked → none`, `paper → none`, `excluded → none`. Прямой `none → paper` discouraged.
- **§5 Инварианты:** все переходы — manual SQL, нет автоматических; `tier` не зависит от `copy_status`; `estimated_capital` не очищается при downgrade.
- **§11.1–§11.3 Pre-action checklists** — что должен сделать владелец проекта **до** UPDATE.
- **§12.3 `estimated_capital` методы** — 4 варианта (`max_daily_volume_30d`, `p99_trade_20x`, `peak_exposure_2x`, `manual`).
- **§13 Open issues:** `copy_status_updated_at` не реализован (см. RF7).
