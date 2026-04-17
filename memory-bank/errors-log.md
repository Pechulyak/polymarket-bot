# Errors Log — что пошло не так и как решили

## Формат записи

---

### [2026-04-17] BUG-801: pnl_status = UNAVAILABLE после CLOSED в whale_trade_roundtrips

- **Симптом:** 10,056 CLOSED roundtrips в whale_trade_roundtrips имели pnl_status = 'UNAVAILABLE' при наличии заполненного net_pnl_usd.
- **Причина:**
  1. SQL функция `settle_resolved_positions()` (migration_phase3_004) закрывала позиции через SETTLEMENT_WIN/SETTLEMENT_LOSS, но НЕ устанавливала:
     - `gross_pnl_usd` (оставался NULL)
     - `pnl_status` (оставался UNAVAILABLE)
  2. Python код логично оставлял статус UNAVAILABLE при gross_pnl_usd = NULL
- **Решение:**
  1. Backfill запрос для существующих данных:
     ```sql
     UPDATE whale_trade_roundtrips
     SET gross_pnl_usd = net_pnl_usd,
         pnl_status = 'CONFIRMED',
         updated_at = NOW()
     WHERE status = 'CLOSED'
       AND pnl_status = 'UNAVAILABLE'
       AND close_type IN ('SETTLEMENT_WIN', 'SETTLEMENT_LOSS')
       AND gross_pnl_usd IS NULL
       AND net_pnl_usd IS NOT NULL;
     ```
     Результат: 10,123 строк обновлено.
  2. Патч живой функции в PostgreSQL (добавлены `gross_pnl_usd` и `pnl_status` в UPDATE)
  3. Обновлён файл `scripts/migration_phase3_004_settle_resolved_positions.sql`
- **Верификация:** Свежие settlement записи (updated_at 2026-04-17 18:22) имеют pnl_status = CONFIRMED и gross_pnl_usd заполнен.
- **Правило:** При добавлении новых колонок (gross_pnl_usd, pnl_status) в существующую таблицу — добавить UPDATE этой колонки во ВСЕ места где изменяется status на CLOSED. Проверять живую функцию в PostgreSQL отдельно от файла миграции.

---

### [2026-04-09] INFRA-002-005.2: credentials выведены в stdout через `docker compose config | grep`

- **Симптом:** В Task Pack этапа 3 была команда `docker compose config | grep -A 15 "polymarket_postgres"`. При выполнении в stdout попали POSTGRES_PASSWORD, GRAFANA_DB_PASSWORD, ORDER_EXECUTOR_DB_PASSWORD, BUILDER_API_KEY/SECRET/PASSPHRASE, DATABASE_URL.
- **Причина:** `docker compose config` разворачивает все `${VAR}` и `env_file: .env` в plain text. `-A 15` гарантированно захватывает блок `environment:` любого сервиса. Я (STRATEGY) дал команду в Task Pack, не подумав про блок env.
- **Решение:** Скомпрометированные секреты в техдолге `INFRA-002-005.2-FOLLOWUP-SECRETS` как блокер для INFRA-002-006.x. Окно эксплуатации = 0 (порт 5433 закрыт).
- **Правило:** В Task Pack запрещены: `docker compose config` без `--quiet` или `> /dev/null`; `grep` с `-A`/`-B`/`-C` контекстом > 1 вокруг имени сервиса; `docker inspect` без `--format` фильтра; `env`, `printenv`, `cat .env`. Безопасные альтернативы: `docker compose config --quiet` (синтаксис), `docker compose config --services` (имена), `docker inspect ... --format '{{...}}'` с явным полем.

---

### [2026-04-09] INFRA-002-005.3: `sed -i` сломал bind mount pg_hba.conf (inode rename)

- **Симптом:** После `sed -i` правки pg_hba.conf на хосте + `pg_ctl reload` PostgreSQL продолжал использовать старую конфигурацию. `pg_hba_file_rules` показывал `host` вместо `hostssl`. MD5 файла на хосте `d84a4be4...`, MD5 файла в контейнере `304c7e12...` (старый baseline).
- **Причина:** `sed -i` атомарно создаёт новый файл и переименовывает поверх старого. Inode меняется. Bind mount Docker удерживает ссылку на старый inode, который продолжает существовать пока контейнер его открывает. Контейнер видит снимок файла на момент своего старта.
- **Решение:** Force-recreate postgres контейнера (этап 3.5). После recreate новый контейнер взял текущий inode, MD5 совпали (`d84a4be4...`), pg_hba_file_rules показал `hostssl`. Downtime ~20 секунд, pipeline восстановился сам.
- **Правило:** Для правки файлов под bind mount **никогда не использовать `sed -i`** (создаёт новый inode). Использовать запись в существующий inode: `cat > file <<EOF`, `tee file`, `python -c "open(...).write()"`. Альтернатива — после любой правки делать force-recreate контейнера. Pre-flight проверка: `stat -c '%i'` файла на хосте и в контейнере должны совпадать после правки.

---

### [2026-04-09] INFRA-002-005.x: STRATEGY дважды поднял ложную тревогу о компрометации/сломанном YAML

- **Симптом:** (1) В этапе 3 задачи 005.2 интерпретировал unified diff как "Roo сломал YAML структуру" — на самом деле YAML был корректным, я неправильно прочитал diff формат. (2) В этапе 3 задачи 005.2 интерпретировал отчёт Roo как "повторная утечка credentials" — на самом деле Roo выполнил `grep -A 2 "ssl"`, env-блок не вывелся.
- **Причина:** Поверхностная проверка фактов перед эскалацией. В первом случае не сверил полный итоговый файл с backup'ом по хэшам. Во втором — не проверил какую именно команду Roo выполнил, прежде чем обвинять.
- **Решение:** В обоих случаях после уточнения подтверждено что всё корректно.
- **Правило:** Перед любой эскалацией ("СТОП", "критично", "rollback") — сверять с фактами из вывода Roo, не с предположениями. Для diff конфиг-файлов всегда: полный diff (без `head`/`grep`) + хэши неизменённых секций. Ложные тревоги обесценивают реальные.

---

### [2026-04-09] INFRA-002-005.x: Roo склеивает этапы в одном отчёте

- **Симптом:** Roo несколько раз пропускал отдельный отчёт по этапу: в 005.2 этап 5 (двойная верификация SSL) был выполнен но не показан отдельно — отчёт пришёл сразу как "этап 6". В 005.3 этап 3.5 (force-recreate) был склеен с этапом 4.
- **Причина:** Неясно — возможно Roo считает короткие технические этапы "неинтересными" для отдельного отчёта.
- **Решение:** В обоих случаях STRATEGY заметил пропуск, потребовал отчёт задним числом, получил.
- **Правило:** STRATEGY обязан проверять что отчёт Roo покрывает **все** этапы Task Pack по номерам, а не только последний. Перед approval финализации — пройтись по чеклисту этапов. Если этап пропущен в отчёте — требовать отдельно, не "по факту видно что прошло".

---

### [2026-04-06] INFRA-002-004: smoke_test.sh упал при переходе на scram-sha-256

- **Симптом:** При переписывании pg_hba.conf с trust на scram-sha-256 — smoke_test.sh упал с 22/23 до 16/7
- **Причина:**
  1. smoke_test.sh подключается через `docker compose exec -T bot psql -h postgres` (TCP)
  2. Наш pg_hba требовал пароль для docker network 172.18.0.0/16
  3. smoke_test.sh не передаёт PGPASSWORD
- **Попытки решения:**
  1. local trust, peer — не помогло (TCP требует пароль)
  2. local trust, host scram — контейнеры упали
  3. Полный rollback — восстановлен дефолтный pg_hba (trust for all)
- **Статус:** ROLLBACK, система восстановлена (22/23 smoke_test)
- **Правило:**
  - smoke_test.sh использует TCP через bot, не socket через postgres
  - trust для docker network 172.18.0.0/16 обязателен для current smoke_test
  - ИЛИ исправить smoke_test.sh перед retry

---

### [2026-03-24] TRD-424: roundtrip_builder не заполняет market_title и market_category

- **Симптом:** При создании записей в whale_trade_roundtrips поля market_title и market_category остаются пустыми (NULL)
- **Причина:** 
  1. Запрос в `_fetch_and_group_buy_trades()` использовал GROUP BY с агрегатными функциями, но не извлекал market_title/market_category из конкретной записи (MIN id)
  2. При GROUP BY PostgreSQL выбирает произвольное значение из группы, не связанное с MIN(id)
- **Попытки решения:**
  1. Добавление wt.market_title, wt.market_category в SELECT и GROUP BY - не помогло (произвольные значения)
  2. Подзапрос с MIN(id) для получения полей - синтаксическая ошибка в SQLAlchemy
  3. FIRST_VALUE() window function - не помогло (GROUP BY конфликтует)
- **Статус:** Требует отдельного исследования
- **Правило:** Для получения полей из "первой" записи в группе использовать DISTINCT ON (PostgreSQL) или отдельный запрос после GROUP BY

---

## Формат записи

---

### [2026-03-17] TRD-412: Ошибка подключения к БД при выполнении reconstruction

- **Симптом:** При запуске backfill скрипт подключался к SQLite (`:memory:`) вместо PostgreSQL
- **Причина:** `settings.database_url` возвращал `sqlite:///:memory:`, не читая из `.env`
- **Решение:** Передавал database_url напрямую в класс:
  ```python
  reconstructor = WhaleRoundtripReconstructor(database_url='postgresql://postgres:Artem15@localhost:5433/polymarket')
  ```
- **Правило:** При использовании SQLAlchemy напрямую - всегда передавать полный database_url, не полагаться на settings

---

### [2026-03-17] TRD-412: NotNullViolation для whale_id/wallet_address

- **Симптом:** При сохранении roundtrips возникала ошибка "null value in column 'wallet_address' violates not-null constraint"
- **Причина:** 781 записей в whale_trades не имеют关联 к whales (whale_id = NULL)
- **Решение:** 
  1. Обновил SQL схему: `ALTER TABLE whale_trade_roundtrips ALTER COLUMN whale_id/wallet_address DROP NOT NULL`
  2. Обновил scripts/migration_whale_trade_roundtrips.sql
- **Проверка:** Backfill успешно завершён - 5333 roundtrips создано
- **Правило:** Для таблиц, связанных с внешними данными (whale_trades) - учитывать orphaned records

---

### [2026-03-18] TRD-412: Settlement detection not working

- **Симптом:** 0 из 100 рынков определены как settled, хотя многие рынки должны быть закрыты
- **Причина:** Polymarket Gamma API возвращает 422 Unprocessable Entity для старых рынков. Возможно:
  1. Рынки удалены из API после завершения
  2. API endpoint изменился
  3. Формат market_id неправильный
- **Решение:** 
  1. Settlement detection приостановлен до выяснения причины
  2. Позиции остаются OPEN если нет явного SELL события
  3. CLOSED/PARTIAL создаются только при наличии SELL в whale_trades
- **Правило:** Использовать paper_trades settlement engine для проверки рабочего resolution API

### [2026-03-18] TRD-412: Settlement detection not implemented

- **Симптом:** 5276 позиций имеют status=OPEN, хотя рынки уже завершились (settlement)
- **Причина:** Алгоритм reconstruction не проверяет Polymarket API для определения resolution рынков
- **Решение:** Нужно добавить:
  1. Settlement detection через Polymarket Gamma API (как в paper_position_settlement.py)
  2. Для OPEN позиций на закрытых рынках - проставить SETTLEMENT_WIN/SETTLEMENT_LOSS
  3. P&L рассчитывается по settlement price
- **Правило:** Использовать paper_position_settlement.py get_market_resolution() для определения settlement

---

### [2026-03-18] TRD-412: No incremental updates

- **Симптом:** Данные не обновляются после 2026-03-17 19:17 - новые whale_trades не добавляются в roundtrips
- **Причина:** Reconstruction запускается один раз как backfill, нет механизма инкрементного обновления
- **Решение:** Нужно добавить:
  1. Проверку новых whale_trades при каждом запуске
  2. Создание roundtrip для новых buy events
  3. Обновление close для новых sell events
- **Правило:** При деплое добавить вызов reconstruction в scheduled job

---

### [2026-03-18] TRD-412: Null fields in whale_trade_roundtrips

- **Симптом:** many fields are null (market_category, whale_id, wallet_address)
- **Причина:** 
  - whale_id/wallet_address - orphaned trades without whale record
  - market_category - Polymarket API doesn't provide this field
- **Решение:** 
  - whale_id/wallet_address - уже исправлено (nullable columns)
  - market_category - оставить nullable, fallback to market_title keywords if needed
- **Правило:** Документировать что market_category недоступен из API

---

## Формат записи
### [ДАТА] Короткое название ошибки
- **Симптом:** что наблюдалось
- **Причина:** почему произошло
- **Решение:** что сделали
- **Правило:** как избежать в будущем

---

### LESSON-006.2-3: Docker published ports + iptables на Ubuntu 24.04

**Context:** INFRA-002-006.FIREWALL, 6 чатов на firewall-задачу.

**Проблема:** Docker при публикации порта (`ports: "0.0.0.0:5433:5432"`) делает DNAT в PREROUTING. Это ломает традиционные подходы:
1. Правила в INPUT chain не видят трафик — он идёт через FORWARD путь.
2. ufw правила бесполезны — DNAT happens раньше ufw chains.
3. DOCKER-USER с `--dport 5433` не матчит — после DNAT dport уже = 5432 (container port).

**Решение:**
- Фильтровать в DOCKER-USER через `-m conntrack --ctorigdstport 5433` (conntrack помнит original dst port до NAT).
- Обязательно правило `--ctstate ESTABLISHED,RELATED -j ACCEPT` **первым**, иначе обратный трафик от контейнера попадает под DROP (source IP контейнера ≠ whitelist).
- Persistence через systemd unit, НЕ через iptables-persistent (несовместим с ufw и Docker managed chains).
- netfilter-persistent отключать на boot.

**Pre-flight для любой firewall-задачи с Docker:** `nft list ruleset` + `iptables --version` (проверить nftables backend) + `cat /etc/docker/daemon.json` (userland-proxy setting).

---

### [2026-04-11] SYS-325: Roo самостоятельно редактировал docker-compose.yml без ⏸ СТОП

- **Симптом:** Roo без ожидания ⏸ СТОП и ревью STRATEGY отредактировал docker-compose.yml (добавил logging для postgres, redis, bot).
- **Причина:** Roo интерпретирует отсутствие явного запрета как разрешение. В TASK PACK не было явного запрета.
- **Решение:** Откат через `git checkout -- docker-compose.yml`. Изменения не применены.
- **Правило:** В каждый TASK PACK добавить явный запрет: "git commit/push — ТОЛЬКО после явного 'подтверждаю коммит' от STRATEGY. Любое редактирование файлов — ТОЛЬКО после явного подтверждения шага."

---

### [2026-04-11] SYS-325: Roo самостоятельно выполнил git commit + push

- **Симптом:** Roo без явного подтверждения STRATEGY выполнил git commit + push.
- **Причина:** Roo интерпретирует отсутствие возражений как подтверждение.
- **Решение:** Коммит оставлен (TASK_BOARD обновление — рутинная задача), но зафиксирован инцидент.
- **Правило:** Любой git commit — ТОЛЬКО после явного "подтверждаю коммит".

---

### [2026-04-11] SYS-323: Docker image scope not pre-defined

- **Симптом:** При ревью Шага 2 не идентифицированы образы вне проекта как неприкосновенные до начала удаления. amneziavpn/amnezia-wg:latest удалён (оказался неактивным дублем — рабочий образ amnezia-awg:latest не пострадал). 3k ui не был выявлен на этапе инвентаризации (запущен вне docker).
- **Причина:** Отсутствовал явный список "неприкосновенных" образов перед началом задачи.
- **Решение:** Перед любым docker image rmi/prune — полная инвентаризация всех образов сервера с явной категоризацией: проект / инфраструктура / неизвестное. Удалять только категорию "проект" и только явным списком.
- **Правило:** Все Docker cleanup задачи должны начинаться с полного `docker images -a` с явным списком "удалить: X, Y, Z" и "не трогать: A, B, C".

---

## Зафиксированные ошибки

### [2026-03-06] market_title сохраняется как NULL в БД

- **Симптом:** Все записи в таблице `whale_trades` имеют `market_title=NULL`, хотя Polymarket API возвращает это поле
- **Причина:** При сохранении whale trades во всех модулях передавалось `market_title=None`:
  - `virtual_bankroll.py` строки ~559, ~677
  - `whale_detector.py` строка ~350
  - `real_time_whale_monitor.py` строка ~371
- **Решение:**
  1. Создана утилита [`src/data/storage/market_title_cache.py`](src/data/storage/market_title_cache.py) — функция `get_market_title(market_id)` с кэшированием (до 100 записей)
  2. Функция использует `PolymarketClient.get_market()` и извлекает поле `question` из ответа API
  3. Обновлены все места вызова:
     - [`src/strategy/virtual_bankroll.py`](src/strategy/virtual_bankroll.py): строки 559, 677 — добавлен вызов `await get_market_title(market_id)`
     - [`src/research/whale_detector.py`](src/research/whale_detector.py): строка ~350 — добавлен вызов
     - [`src/research/real_time_whale_monitor.py`](src/research/real_time_whale_monitor.py): строка ~371 — добавлен вызов
- **Проверка:** Все файлы прошли `python3 -m py_compile` без ошибок
- **Правило:** Использовать `get_market_title()` для получения title при наличии market_id

---

### [2026-02-28] Киты не сохраняются в БД (ИСПРАВЛЕНО)

- **Симптом:** В памяти: 10-35 tracked whales, в БД: 0 записей. Логи показывают: `whale_save_failed error='column "total_volume_usd" of relation "whales" does not exist'`
- **Причина:** Таблица `whales` в БД не имела колонок, требуемых кодом `_save_whale_to_db()` в whale_detector.py:
  - total_volume_usd
  - avg_trade_size_usd
  - status
  - trades_last_3_days
  - days_active
- **Решение:** Добавлены колонки через ALTER TABLE:
  ```sql
  ALTER TABLE whales ADD COLUMN IF NOT EXISTS total_volume_usd DECIMAL(20, 8) NOT NULL DEFAULT 0;
  ALTER TABLE whales ADD COLUMN IF NOT EXISTS avg_trade_size_usd DECIMAL(20, 8) NOT NULL DEFAULT 0;
  ALTER TABLE whales ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'discovered';
  ALTER TABLE whales ADD COLUMN IF NOT EXISTS trades_last_3_days INTEGER NOT NULL DEFAULT 0;
  ALTER TABLE whales ADD COLUMN IF NOT EXISTS days_active INTEGER NOT NULL DEFAULT 0;
  ```
- **Проверка:** COUNT(*) FROM whales = 15+, киты сохраняются со статусом discovered
- **Правило:** Обновить scripts/init_db.sql чтобы схема соответствовала коду

### [2026-02-28] Stage 2 — киты не сохраняются в БД

- **Симптом:** В памяти 10 tracked whales, Quality=0, в БД 0 записей. Логи не показывают ошибок сохранения.
- **Причина:**
  1. `known_whales_loaded` показывало 10 whales — это из старой БД (кеш в памяти после перезапуска)
  2. WhaleDetector использует `database_url` из env, но в whale-detector контейнере был неправильный DATABASE_URL
  3. После исправления DATABASE_URL в docker-compose.yml — сохранение всё равно не работает
  4. Возможная причина: whales не проходят `daily_trade_threshold` (5 trades/day), поэтому не попадают в tracked list
- **Решение (в процессе):**
  - Исправлен DATABASE_URL в docker-compose.yml: `postgresql://postgres:156136ar@postgres:5432/polymarket`
  - Добавлены логи `save_whale_to_db` для диагностики
  - Изменена логика: теперь сохраняются ВСЕ discovered киты, не только quality
- **Правило:** Всегда проверять DATABASE_URL через `docker compose exec <service> env | grep DATABASE`

### [2026-02] PostgreSQL порт
- **Симптом:** подключение к БД падало
- **Причина:** стандартный порт 5432 вместо 5433

### [2026-03-02] Подключение к неправильной БД — postgres вместо polymarket

- **Симптом:** При выполнении SQL-запросов к таблице `whales` получал 0 записей: `SELECT COUNT(*) FROM whales;` → 0
- **Причина:** Использовал базу данных `postgres` по умолчанию, хотя проект использует БД `polymarket`
- **Решение:** Указал правильную БД в psql: `-d polymarket`
  ```bash
  docker exec -i polymarket_postgres psql -U postgres -d polymarket -c "SELECT COUNT(*) FROM whales;"
  # Результат: 1084
  ```
- **Правило:** Всегда указывать `-d polymarket` при подключении к PostgreSQL в этом проекте. Имя БД указано в docker-compose.yml
- **Решение:** исправить DATABASE_URL на порт 5433
- **Правило:** PostgreSQL всегда на 5433 в этом проекте

---

### [2026-02] WhaleDetector AttributeError — self.config не сохранялся
- **Симптом:** контейнер whale-detector падал сразу после запуска
- **Причина:** в whale_detector.py `__init__` принимал `config` но не делал `self.config = config`
- **Решение:** добавить `self.config = config` в `__init__` после строки 148
- **Правило:** при создании класса всегда проверять что все параметры `__init__` сохраняются в `self`

---

### [2026-03-01] E2E Test — fromisoformat error в whale_tracker.py

- **Симптом:** E2E тест падал с ошибкой `TypeError: fromisoformat() argument must be str, datetime or None`
- **Причина:** whale_tracker.py вызывал `datetime.fromisoformat()` без проверки типа данных, полученных из БД
- **Решение:** Добавлена проверка типа данных и преобразование через `ast.literal_eval()` для кортежей
- **Правило:** Всегда проверять тип данных полученных из БД перед вызовом методов datetime

### [2026-03-01] E2E Test — AttributeError в WhaleTracker

- **Симптом:** Ошибка `AttributeError: 'WhaleTracker' object has no attribute 'config'`
- **Причина:** WhaleTracker.__init__ не инициализировал self.config
- **Решение:** Добавлена инициализация self.config = config в WhaleTracker.__init__
- **Правило:** При создании класса всегда проверять что все параметры __init__ сохраняются в self

---

### [2026-02-28] Whale Stats Incorrect — win_rate и profit были некорректны

#### Проблема 1: Некорректный win_rate
- **Симптом:** win_rate показывал процент от всех сделок кита (buy сделки)
- **Причина:** Считалось что "buy" = "win", но это не так! Покупка "Yes" - это просто позиция, не выигрыш
- **Решение:**
  - Введён `stats_mode: REALIZED` - статистика основана на реальных результатах копирования
  - win_rate теперь вычисляется как: realized_pnl > 0 / total_copied_trades
  - Используется realized_pnl из скопированных сделок в БД
- **Правило:** Не путать buy сделку с выигрышем. Win = позиция закрылась с прибылью

#### Проблема 2: Некорректный profit
- **Симптом:** profit показывал volume, а не реальную прибыль
- **Причина:** API не предоставляет PnL, использовался volume как прокси
- **Решение:**
  - profit теперь = realized_pnl из скопированных сделок
  - Добавлено поле `data_capability: PARTIAL` в PROJECT_STATE
- **Правило:** Не использовать volume как замену profit

#### Проблема 3: Разные risk_score в detector и tracker
- **Симптом:** risk_score вычислялся в двух местах с разной логикой
- **Причина:** Не было единого source-of-truth
- **Решение:**
  - risk_score_source_of_truth: tracker
  - whale_detector использует risk_score из whale_tracker
  - Единая логика в QUALITY_WHALE_CRITERIA
- **Правило:** Всегда иметь единый source-of-truth для ключевых метрик

#### Проблема 4: API Capability
- **Симптом:** Ожидали от API данные, которых нет
- **Причина:** Polymarket Data API НЕ предоставляет: direct PnL, win/loss статус сделок
- **Решение:**
  - Добавлен аудит в docs/data_capability_audit.md
  - data_capability: PARTIAL
  - stats_mode: REALIZED (только при копировании получаем реальные результаты)
- **Правило:** Всегда проверять фактические возможности API перед использованием
