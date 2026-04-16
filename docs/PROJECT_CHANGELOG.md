# PROJECT CHANGELOG

Версия: v1.0  
Формат: краткий лог изменений (без технических деталей)

---

## ПРАВИЛА ВЕДЕНИЯ

1. Записываются ВСЕ задачи (TRD / SYS / STRAT и др.)
2. Только ключевая идея — без логов, SQL и кода
3. Максимум **15 строк на одну задачу**
4. Описывается результат, а не процесс
5. Один блок = одна задача

---

### INFRA-003 — Backup Policy

**Дата:** 2026-04-12

**Описание:**  
Реализована автоматизированная политика резервного копирования БД.

**До:**  
Бэкапы отсутствовали. Потеря postgres volume = потеря всех данных без возможности восстановления.

**После:**  
Ежедневный pg_dump (03:00 UTC) → GPG AES256 → Backblaze B2 (retention 7d). Restore test верифицирован (16 таблиц, 17135 roundtrips). Telegram alert при failure.

**Влияние:**  
scripts/backup_db.sh, scripts/backup_restore_test.sh, crontab, pipeline_monitor, .env

---

## ФОРМАТ ЗАПИСИ

### <TASK_ID> — <Краткое название>

**Дата:** YYYY-MM-DD  

**Описание:**  
<1–2 предложения, суть изменения или проблемы>

**До:**  
<что было неправильно / отсутствовало>

**После:**  
<что стало после выполнения задачи>

**Влияние:**  
<на какие части системы повлияло>

**Зависимости / риски (опционально):**  
<если есть важные последствия или ограничения>

---

## ANA-501 — Daily Whale Alert Monitor

**Дата:** 2026-04-16

**Описание:**  
Создан ежедневный мониторинг китов (cron 08:00 UTC).

**До:**  
Отсутствовал механизм алертов по проблемам китов.

**После:**  
5 проверок: неактивность paper/tracked, skip rate, WR деградация, новые кандидаты. Пороги в strategy_config.

**Влияние:**  
scripts/run_daily_whale_alert.py, scripts/migration_ana501_whale_alert_thresholds.sql, crontab

**Зависимости / риски:**  
Skip rate window = MAX(reviewed_at, now-7d) для корректного учёта новых китов.

---

## ПРИМЕР

### TRD-413 — Whale trades ingestion audit

**Дата:** 2026-03-23  

**Описание:**  
Выявлена критическая потеря данных при сборе whale_trades.

**До:**  
Использовался глобальный feed с лимитом 500 сделок, без per-wallet загрузки.

**После:**  
Определена необходимость перехода на targeted API fetch.

**Влияние:**  
Затронуты whale_tracker, whale_detector, логика квалификации китов.

**Зависимости / риски:**  
Требуется redesign ingestion pipeline.

---

### TRD-419 — Migration to activity-based whales schema

**Дата:** 2026-03-23  

**Описание:**  
Перевод логики китов с legacy полей на activity-based модель.

**До:**  
Использовались некорректные метрики (win_rate, total_profit_usd).

**После:**  
Введены поля activity: trades_count, days_active, volume.

**Влияние:**  
Обновлены whale_detector, whale_tracker и схема БД.

---

### PHASE1-001 — WhaleTradesRepo

**Дата:** 2026-04-02  

**Описание:**  
Создание единой точки записи whale_trades с валидацией и счётчиками.

**До:**  
Разные модули (whale_detector, whale_tracker) писали в БД напрямую, без централизованной валидации.

**После:**  
WhaleTradesRepo обеспечивает统一的 валидацию (side, size, price), дедупликацию по tx_hash, счётчики saved/rejected/duplicates.

**Влияние:**  
Новые модули: src/db/whale_trades_repo.py, src/db/__init__.py. Тесты: tests/test_whale_trades_repo.py (7/7 passed).

---

### PHASE1-002: whale_detector → WhaleTradesRepo

**Дата:** 2026-04-02  

**Описание:**  
Переключение whale_detector.save_trade_to_db() на WhaleTradesRepo.

**До:**  
save_trade_to_db() использовал async engine + save_whale_trade() напрямую.

**После:**  
Делегирует в WhaleTradesRepo: валидация (side, size, price), дедупликация, счётчики.

**Влияние:**  
 whale_detector.py — изменения в import, __init__, set_database, _ensure_database, save_trade_to_db, _paper_poll_loop. Логирование repo stats каждые 30 сек.

---

### PHASE1-003: whale_tracker → WhaleTradesRepo

**Дата:** 2026-04-02  

**Описание:**  
Переключение whale_tracker.save_whale_trade() на WhaleTradesRepo.

**До:**  
save_whale_trade() использовал async engine + save_whale_trade() из whale_trade_writer.

**После:**  
Делегирует в WhaleTradesRepo: валидация (side, size, price), дедупликация, счётчики.

**Влияние:**  
whale_tracker.py — изменения в import, __init__, set_database, _ensure_database, save_whale_trade. Старый код закомментирован (rollback-ready).

**Зависимости / риски:**  
whale_trade_writer.py → DEPRECATED, используется только в virtual_bankroll (Фаза 2+).

---

### PHASE1-004: Pipeline Monitor

**Дата:** 2026-04-02  

**Описание:**  
7 проверок здоровья pipeline + Telegram алерты.

**До:**  
Отсутствовала централизованная система мониторинга pipeline.

**После:**  
scripts/pipeline_monitor.py — 7 проверок: whale_trades, paper_trades, roundtrips, containers, data quality. Telegram: WARNING/CRITICAL каждые 30 мин, OK раз в 6ч.

**Влияние:**  
Таблица pipeline_health_log для истории. Cron: */30 * * * *.

---

### PHASE1-005 — Финальная верификация Фазы 1

**Дата:** 2026-04-03

**Описание:**  
24-часовое наблюдение pipeline: WhaleTradesRepo + whale_detector + whale_tracker + Pipeline Monitor.

**До:**  
Не было подтверждения стабильной работы pipeline в течение длительного времени.

**После:**  
- 1,339 whale_trades за 24ч через repo
- rejected=0, zero_size=0
- Pipeline monitor: 56 проверок, 4 OK, 52 WARNING (только category до backfill)
- Все 5 контейнеров healthy, 0 restarts
- smoke_test PASS

**Влияние:**  
Фаза 1 завершена, готовность к Фазе 2.

**Зависимости / риски (опционально):**  
3 пути записи whale_trades вне repo (Фаза 2): virtual_bankroll, whale_poller, real_time_whale_monitor

---

## 2026-04-03

### PHASE1.5-001: Аудит Kelly sizing

**Дата:** 2026-04-03  

**Описание:**  
Аудит текущего Kelly sizing в trigger copy_whale_trade_to_paper.

**До:**  
trigger использовал hardcoded bankroll=$100, fraction=0.25, cap=$2. Все 1738 paper_trades имели kelly_size=$2 (flat), size_usd кита не использовался в расчёте.

**После:**  
Определена необходимость proportional sizing. Downstream (main.py) использует kelly_size приоритетно — безопасно для изменения.

**Влияние:**  
trigger, paper_trades table

---

### PHASE1.5-002: Strategy config + estimated capital

**Дата:** 2026-04-03  

**Описание:**  
Добавление strategy_config таблицы и estimated_capital поля в whales.

**До:**  
Отсутствовала конфигурация для Kelly sizing.

**После:**  
Создана strategy_config таблица (kelly_fraction, max_position_pct, min_trade_size_usd, our_bankroll). Добавлены поля whales.estimated_capital + capital_estimation_method. 0x32ed: estimated_capital=$200,000 (manual).

**Влияние:**  
БД: new tables, new columns

---

### PHASE1.5-003: Proportional Kelly sizing

**Дата:** 2026-04-03  

**Описание:**  
Обновление trigger copy_whale_trade_to_paper на proportional sizing.

**До:**  
Flat $2 kelly_size для всех сделок.

**После:**  
Формула: (whale_size / whale_capital) * bankroll * kelly_fraction. Cap: max_position_pct (5%) of bankroll. Floor: min_trade_size_usd ($1), trades below skipped. Конфиг: kelly_fraction=0.25, max_position_pct=0.05, our_bankroll=$1000. Rollback: scripts/rollback_trigger_phase1.5.sql.

**Влияние:**  
trigger, paper_trades table

---

### PHASE1.5-004: Estimated capital для paper кита

**Дата:** 2026-04-03  

**Описание:**  
Установка estimated_capital для paper кита 0x32ed.

**До:**  
Поле estimated_capital отсутствовало.

**После:**  
0x32ed: estimated_capital=$200,000, method=manual. Объединено с PHASE1.5-001.

**Влияние:**  
whales table

---

### PHASE1.5-005: Pipeline верификация

**Дата:** 2026-04-04  

**Описание:**  
Верификация proportional Kelly sizing pipeline.

**До:**  
Верификация не проводилась.

**После:**  
Trigger содержит strategy_config (новый код подтверждён). Тестовые данные: 4/4 pass (PHASE1.5-003). Живые данные: кит не торговал после деплоя — верификация недоступна.

**Влияние:**  
trigger, documentation

**Готовность к Фазе 2:**  
Да (тестовые данные валидны)

---

### INFRA-002-006: PostgreSQL port 5433 firewall hardening

**Дата:** 2026-04-11

**Описание:**
Закрытие внешнего доступа к PostgreSQL (порт 5433) для всех IP кроме Сервера 2 (62.60.233.100).

**До:**
Порт 5433 открыт миру. Попытки фильтрации через iptables INPUT, ufw и DOCKER-USER с `--dport 5433` не работали из-за Docker DNAT в PREROUTING.

**После:**
Фильтрация через DOCKER-USER chain с `-m conntrack --ctorigdstport 5433`. Три правила в порядке: ESTABLISHED/RELATED ACCEPT → 62.60.233.100 ACCEPT → DROP. Persistence через systemd unit `docker-firewall-rules.service` с idempotent cleanup loop. netfilter-persistent отключён для избежания конфликта на boot.

**Влияние:**
firewall, systemd, docker networking, network security

---

### INFRA-002-007: End-to-end connection test from Server 2

**Дата:** 2026-04-11

**Описание:**
Верификация подключения с Сервера 2 к PostgreSQL Сервера 1 через SSL для Grafana dashboards.

**До:**
Инфраструктура (pg_hba, SSL, firewall) развёрнута, но end-to-end тест с Сервера 2 не проводился.

**После:**
grafana_reader: SSL TLSv1.3 + AES-256-GCM, SELECT работает на всех аналитических таблицах (whales=6957, paper_trades=4603, whale_trades=39872), write-операции (CREATE, UPDATE) падают с permission denied. Grafana PostgreSQL data source настроен (host 212.192.11.92:5433, sslmode=require), Save & Test = Database Connection OK.

order_executor: коннект + SSL работают, но обнаружено несоответствие прав назначению — только SELECT на аналитических таблицах, нет write, нет pending_orders schema. Заведена отдельная задача INFRA-002-AUDIT-ORDER-EXEC.

**Влияние:**
Grafana data source, monitoring pipeline

---

### INFRA-002-008: Security baseline audit

**Дата:** 2026-04-11

**Описание:**
Финальный read-only аудит 9 областей security posture БД после закрытия эпика INFRA-002. Baseline зафиксирован в отдельном документе.

**До:**
Отсутствовал единый reference документ состояния безопасности БД.

**После:**
Создан `docs/INFRA-002-SECURITY-BASELINE.md`. Network/SSL/pg_hba/Roles/Secrets — PASS. Обнаружены gaps: Logging (minimal), Backups (missing), Host hardening (SSH PasswordAuth, no fail2ban), Documentation (no user runbook). Gaps заведены как отдельные задачи: INFRA-003-BACKUP-POLICY, SEC-501-HOST-HARDENING, postgres-logging-hardening, firewall-startup-race-fix, user-provisioning-runbook. Эпик INFRA-002 закрыт полностью (8/8 задач).

**Влияние:**
documentation, security posture reference

---

## ОГРАНИЧЕНИЯ

Запрещено в CHANGELOG:

- логи выполнения
- SQL-запросы
- куски кода
- длинные объяснения
- повторение TASK_BOARD
- метрики (они в snapshot)
- описание “как делали”

---

## ПРИНЦИП

CHANGELOG должен отвечать на вопрос:

> Что изменилось в системе и зачем это было сделано?

А не:

> Как именно мы это реализовывали.

---

## ИТОГ

CHANGELOG = краткая история решений, а не технический отчёт