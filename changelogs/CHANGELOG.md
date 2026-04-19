# CHANGELOG

## 2026-04

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-04-19 | W-001 | Whale Detection Pipeline: whale_detector.py active, реализован |
| 2026-04-19 | W-002 | Whale Tracking Database: WhaleTradesRepo — единая точка записи |
| 2026-04-19 | W-003 | Strategy Metrics Engine: Kelly sizing + materialized views реализованы |
| 2026-04-19 | W-004 | Copy Trading Engine Integration: copy_trading_engine.py отключён |
| 2026-04-19 | TRD-402 | Goals: populate size correctly, populate opportunity_id from paper_trades, populate market_title, fix gas cost units, ensure new VIRTUAL trades are analytically valid |
| 2026-04-19 | SYS-322 | PRE-PROD-SECRETS-ROTATION: ротация секретов перед переходом на live. Приоритет: БЛОКЕР |
| 2026-04-19 | BUG-701 | Исправлена ссылка на days_active_7d в refresh_qualification() и update_whale_activity_counters() |
| 2026-04-19 | TRD-401 | Goals: validate trades data integrity, detect zero-size trades, verify PnL fields, verify gas cost values, check market metadata completeness |
| 2026-04-19 | FIN-401 | Fix virtual bankroll logic: capital blocked only on executed trade open and returned only on trade close |
| 2026-04-19 | TRD-409 | Completed (details in PROJECT_STATE) |
| 2026-04-19 | TRD-411 | Completed (details in PROJECT_STATE) |
| 2026-04-19 | TRD-412 | Создание whale_trade_roundtrips table и логики реконструкции позиций китов |
| 2026-04-19 | TRD-413 | Whale trades ingestion incomplete (~99% loss for some whales). Root cause: global 500-trade limit + no per-wallet backfill |
| 2026-04-19 | TRD-421 | Completed (details in PROJECT_STATE) |
| 2026-04-19 | TRD-420-A | Targeted fetch trades для китов с copy_status='paper' каждые 30 сек |
| 2026-04-19 | TRD-420-B | Targeted fetch trades для tracked китов каждые 5 мин |
| 2026-04-19 | ANA-502 | Миграция для хранения результатов еженедельного AI анализа |
| 2026-04-19 | ANA-502-SQL | Финальные SQL-запросы для еженедельного AI-анализа китов |
| 2026-04-19 | INFRA-002-004.4 | Применение pg_hba.conf через docker cp + pg_reload_conf |
| 2026-04-19 | INFRA-002-005.2 | Включение SSL в PostgreSQL: mount config/ssl/ + SSL параметры, force-recreate postgres |
| 2026-04-19 | INFRA-002-005.3 | Замена host → hostssl в pg_hba.conf для grafana_reader и order_executor |
| 2026-04-19 | INFRA-002-006.FIREWALL | Firewall hardening: DOCKER-USER chain + conntrack --ctorigdstport 5433 |
| 2026-04-19 | INFRA-002-006.1b | Firewall persistence: systemd unit /etc/systemd/system/docker-firewall-rules.service |
| 2026-04-19 | INFRA-002-007 | Тест полного подключения с Сервера 2: grafana_reader SSL TLSv1.3 AES-256-GCM, SELECT OK, writes denied |
| 2026-04-19 | INFRA-002-008 | 9-этапный read-only security baseline audit |
| 2026-04-19 | INFRA-002-AUDIT-ORDER-EXEC | order_executor permissions: только SELECT на 5 таблицах, нет write |
| 2026-04-19 | INFRA-003 | Backup Policy: нет автоматического backup |
| 2026-04-19 | SEC-501-HOST-HARDENING | SSH hardening: PermitRootLogin=yes, PasswordAuthentication=yes, no fail2ban |
| 2026-04-19 | postgres-logging-hardening | log_connections=off, log_disconnections=off, minimal observability |
| 2026-04-19 | firewall-startup-race-fix | Startup race window ~seconds, pg_hba reject компенсирует |
| 2026-04-19 | user-provisioning-runbook | Процедура добавления user описана в pg_hba.conf комментариях |
| 2026-04-19 | SYS-309 | Daily Data Audit Snapshot: cron intentionally disabled, script kept for manual use |
| 2026-04-19 | SYS-330 | trade_duplicate rate flood: дедупликация работает корректно, риск только рост лог-файла |
| 2026-04-19 | BUG-603 | Dedup filter переключён на opportunity_id (paper_trades.id) |
| 2026-04-19 | BUG-604 | Bankroll reconciliation из таблицы trades |
| 2026-04-19 | BUG-801 | Audit pnl_status UNAVAILABLE в whale_trade_roundtrips: backfill 10,123 rows, smoke_test 24/24 PASS |
| 2026-04-19 | BUG-504 | Fixed false new_trades=50 log: save_whale_trade() теперь возвращает bool на основе INSERT rowcount |
| 2026-04-19 | BUG-502 | Verified real-time whale trade ingestion. Paper poll (30s) и tracked poll (5min) loops работают независимо |
| 2026-04-16 | ANA-501 | Daily Whale Alert Monitor: Cron 08:00 UTC, 5 SQL checks, Telegram alerts |
| 2026-04-15 | SYS-336 | Kelly sizing fix: min_trade_size_usd=$0.01 → $1.00, фильтр кита >= 1% депозита, динамический bankroll |
| 2026-04-15 | SYS-335 | smoke_test freshness check: Check A исправлен (MAX → COUNT WHERE), Check B удалён. Результат: 24/24 PASS |
| 2026-04-14 | SEC-501 | SSH hardening: PasswordAuthentication yes → no, PermitRootLogin yes → prohibit-password, fail2ban установлен |
| 2026-04-14 | SYS-331 | Исправление застрявших roundtrips: run_settlement.sh cron не работал. Закрыто 37 roundtrips, обновлено 2979 китов |
| 2026-04-12 | SYS-334 | Исправление market_category в whale_trade_roundtrips: заполнено через JOIN. 17,217 records updated |
| 2026-04-11 | SYS-328-AUDIT | Инвентаризация файлов: 44 .md, 13 migration_*.sql |
| 2026-04-11 | SYS-329 | Политика хранения логов: journald 1G/7d + docker json-file 50m×3 + logrotate daily×7 |
| 2026-04-11 | SYS-333 | Исправление rsyslog flood: missing log files (ufw.log, mail.log, mail.err). Verified: 0 flood entries/min |
| 2026-04-11 | PHASE4-001 | Аудит данных: схема, JOINs, формулы PnL. Report: docs/audit/PHASE4-001-summary.md |
| 2026-04-10 | INFRA-002-006.0b | Ротация POSTGRES_PASSWORD: Audit + rotation completed, containers recreated |
| 2026-04-05 | PHASE3-007 | Верификация end-to-end settlement в БД: Ручной запуск 09:33 UTC — УСПЕШНО |
| 2026-04-05 | PHASE4-003 | Materialized view paper_portfolio_state created: initial_bankroll=$1000, realized_pnl=-$46.62, current_balance=$953.38 |
| 2026-04-05 | PHASE4-004 | Стандартизация PnL формулы на our_pnl_v2 = whale_pnl * (kelly_size / whale_size) |
| 2026-04-05 | PHASE4-005 | Created refresh_views.sh, cron (15 */2 * * *), 3 view checks to smoke_test.sh. All 23 checks pass |
| 2026-04-05 | PHASE4-006 | Dynamic Kelly: trigger использует dynamic bankroll из paper_portfolio_state view |

---

## 2026-03

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-03-31 | BUG-602 | Bankroll restore из БД при рестарте (больше нет $100 hardcode reset) |
| 2026-03-31 | BUG-601-FIX | Settlement переключён с Gamma API на CLOB API (459 trades закрыто) |
| 2026-03-31 | TRD-430 | Pipeline audit завершён (timezone hypothesis отклонена) |
| 2026-03-30 | TRD-408 | Fix traded_at: теперь использует API timestamp вместо DB insert time |
| 2026-03-29 | STRAT-701 | Whale copy selection: добавлен copy_status column, trigger фильтрует по 'paper', pipeline unfrozen |
| 2026-03-27 | ARC-503 | Remove legacy fields is_winner and profit_usd из whale_trades (код + БД) |
| 2026-03-26 | TRD-427b | Fix: исправлен баг TypeError в _update_whales_pnl() — print() аргумент был строкой вместо списка |
| 2026-03-26 | TRD-427 | Fix: roundtrip_builder теперь запускает --settle автоматически каждые 2 часа |
| 2026-03-26 | TRD-426 | Fix: исправлены tier пороги (HOT: 1d, WARM: 7d), пересчитаны тиры |
| 2026-03-26 | SYS-601-FIX | Fix: устранено дублирование roundtrip jobs (main.py → container), увеличен интервал 30min → 2h |
| 2026-03-26 | ARC-502-D | Fix: обновление P&L китов через wallet_address вместо whale_id (+461 whales, +2266 roundtrips) |
| 2026-03-26 | ARC-502-C | Roundtrip Builder: settlement через CLOB API (+2039 CLOSED, +$680K P&L) |
| 2026-03-25 | ARC-502-B | Fix: fuzzy matching close для short selling (+27 CLOSED) |
| 2026-03-22 | TRD-422 | Добавлен market_category в whale_trades, унифицирован INSERT |
| 2026-03-22 | TRD-423 | Fix whale_trades ingestion: _database_url → database_url |
| 2026-03-22 | ARC-501 | Миграция whales: удалены 8 legacy полей, добавлены 7 P&L полей |
| 2026-03-22 | ARC-502-A | Roundtrip Builder: создание OPEN roundtrips из BUY событий |

---

*Обновлено: 2026-04-19*
