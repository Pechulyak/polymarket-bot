markdown# INFRA-002 Security Baseline — PostgreSQL Database Access

**Дата аудита:** 2026-04-11  
**Скоуп:** Сетевой и аутентификационный слой доступа к PostgreSQL контейнера `polymarket_postgres` (Сервер 1, 212.192.11.92:5433)  
**Статус эпика:** INFRA-002 CLOSED (8/8 задач)  
**Следующий review:** 2026-07-11 (через 3 месяца) или при любом изменении сетевой конфигурации

---

## Назначение документа

Фиксация текущего security posture базы данных после завершения эпика INFRA-002. Используется как:
- Reference для будущих audit'ов (сверка что ничего не откатилось)
- Точка отсчёта для hardening-задач
- Частичная замена отсутствующего user-provisioning runbook

---

## Архитектура доступа
Internet ──┐
│
[Firewall: iptables DOCKER-USER]
│
├─── 62.60.233.100 (Сервер 2) ──► SSL ──► pg_hba hostssl ──► grafana_reader (SELECT only)
│                                                      └──► order_executor (SELECT only, see AUDIT)
│
└─── ALL OTHER IPs ──► DROP

**Двухуровневая защита:** firewall (сетевой) + pg_hba.conf reject (аутентификационный). Compensating controls документированы ниже.

---

## 1. Сетевой слой — ✅ PASS

| Проверка | Результат |
|---|---|
| Firewall DOCKER-USER chain | 3 правила в правильном порядке |
| Правило 1 | ESTABLISHED,RELATED ACCEPT (ctorigdstport 5433) |
| Правило 2 | `-s 62.60.233.100` ACCEPT (ctorigdstport 5433) |
| Правило 3 | DROP (ctorigdstport 5433) |
| DROP counter на момент аудита | 913 пакетов / 54756 байт (подтверждение активной работы) |
| Persistence | systemd unit `docker-firewall-rules.service` (enabled + active) |
| Idempotency | Cleanup loop + 3 ExecStart, выдерживает 3+ restart |
| netfilter-persistent | disabled (избежание конфликта на boot) |
| docker-compose.yml bind | `0.0.0.0:5433:5432` зафиксирован в git |
| Внешний test | C Windows без VPN — timeout ✅ |

**Known issue:** startup race window (~секунд) между `docker.service` start и `docker-firewall-rules.service` start. Компенсируется pg_hba reject вторым слоем. См. `firewall-startup-race-fix` в открытых задачах.

---

## 2. Транспортный слой (SSL) — ✅ PASS

| Параметр | Значение |
|---|---|
| `ssl` | on |
| `ssl_cert_file` | `/etc/postgresql/ssl/server.crt` (bind mount `:ro`) |
| `ssl_key_file` | `/etc/postgresql/ssl/server.key` (bind mount `:ro`) |
| `ssl_ciphers` | `HIGH:MEDIUM:+3DES:!aNULL` (см. accepted risk 2) |
| `ssl_min_protocol_version` | TLSv1.2 (фактически все сессии TLSv1.3, см. risk 3) |
| `password_encryption` | scram-sha-256 |
| Cert subject | `CN=polymarket-postgres, O=PolymarketBot, C=US` |
| Cert validity | 2026-04-09 ... 2036-04-06 (10 лет, self-signed) |
| Реальная сессия Grafana | TLSv1.3 + TLS_AES_256_GCM_SHA384 |

---

## 3. pg_hba.conf / Аутентификация — ✅ PASS

Файл `config/pg_hba.conf` примонтирован как read-only в контейнер. Правила (порядок критичен):

| # | Type | Database | User | Address | Method |
|---|---|---|---|---|---|
| 1 | local | all | all | (unix socket) | trust |
| 2 | host | all | all | 172.18.0.0/16 | trust (Docker network) |
| 3 | host | all | all | 127.0.0.1/32 | trust (accepted risk 1) |
| 4 | host | all | all | ::1/128 | trust |
| 5 | hostssl | polymarket | grafana_reader | 62.60.233.100/32 | scram-sha-256 |
| 6 | hostssl | polymarket | order_executor | 62.60.233.100/32 | scram-sha-256 |
| 7 | host | all | all | 0.0.0.0/0 | reject |
| 8 | host | all | all | ::0/0 | reject |

`pg_hba_file_rules` verified: все 8 правил загружены в память PostgreSQL, соответствуют файлу.

---

## 4. Роли и авторизация — ✅ PASS (+ known issue)

| Role | Superuser | Login | Scope | Access |
|---|---|---|---|---|
| postgres | yes | yes | Local only (через unix socket + Docker network trust) | Full |
| grafana_reader | no | yes | External (62.60.233.100 only, hostssl) | SELECT on 16 tables |
| order_executor | no | yes | External (62.60.233.100 only, hostssl) | SELECT on 5 tables ⚠️ |

**grafana_reader SELECT scope (16):** api_health, bankroll, fee_schedule, market_data, market_resolutions, opportunities, paper_trade_notifications, paper_trades, pipeline_health_log, positions, risk_events, strategy_config, trades, whale_trade_roundtrips, whale_trades, whales.

**order_executor SELECT scope (5):** market_resolutions, paper_trades, strategy_config, whale_trades, whales.

**⚠️ Known issue:** order_executor имеет только READ права, нет write, нет таблицы `pending_orders` или аналога. Имя пользователя вводит в заблуждение — фактически это второй read-only user. Отслеживается задачей `INFRA-002-AUDIT-ORDER-EXEC`. Блокирует live order execution.

---

## 5. Секреты — ✅ PASS

| Проверка | Результат |
|---|---|
| `.env` в `.gitignore` | yes (`.env`, `.env.local`, `.env.*.local`) |
| `.env` в git history | No (никогда не коммитился) |
| Permissions `.env` | `-rw-------` (600, root only) |
| Переменные | POLYMARKET_PRIVATE_KEY, POLYMARKET_API_KEY/SECRET, BUILDER_API_KEY/SECRET, POSTGRES_PASSWORD, GRAFANA_DB_PASSWORD, ORDER_EXECUTOR_DB_PASSWORD |
| Hardcoded секреты в git-tracked коде | `Artem15` найден в 3 файлах (accepted risk 4 + techdebt) |
| Fallback строки "password" | 1 файл (`real_time_whale_monitor.py`, techdebt) |

**Уточнение к SYS-322:** хранилище `.env` чистое. Утечка 5 скомпрометированных секретов происходит через исторические артефакты (старые hardcoded строки в `src/strategy/whale_roundtrip_reconstructor.py`, `tests/test_whale_trades_repo.py`, `memory-bank/errors-log.md`), а не через утечку `.env`. Ротация перед live обязательна даже если код будет очищен.

---

## 6. Логирование — ⚠️ MINIMAL

| Параметр | Текущее значение | Рекомендация |
|---|---|---|
| log_connections | off | **on** |
| log_disconnections | off | **on** |
| log_hostname | off | ok (PII-safe) |
| log_statement | none | `ddl` (аудит схемы) |
| log_min_messages | warning | ok |
| log_min_error_statement | error | ok |
| log_line_prefix | `%m [%p]` | `%m [%p] %u@%d from %h ` |

**Compensating observation:** PostgreSQL пишет FATAL для всех отвергнутых подключений. Аудит показал реальные события (`85.11.167.232` scanner попытки до применения firewall, `keycloak`/`kong`/`n8n`/`superset` credential stuffing по типовым именам).

Отслеживается задачей `postgres-logging-hardening`.

---

## 7. Backups — ❌ MISSING

| Проверка | Результат |
|---|---|
| Автоматический `pg_dump` (cron/systemd) | отсутствует |
| Backup скрипты в `scripts/` | отсутствуют |
| Ручные dumps | 2 файла (последний 2026-04-09, 22 MB) |
| Off-site copy | нет |
| Encryption at rest | нет |
| Restore test procedure | нет |
| Retention policy | нет |

**Отслеживается задачей `INFRA-003-BACKUP-POLICY`. 🔴 БЛОКЕР для live execution.**

---

## 8. Host hardening (upstream risk) — ❌ GAPS

SSH-слой хоста имеет известные дыры, которые **обходят network security INFRA-002**: компрометация SSH → shell → `.env` → POSTGRES_PASSWORD → полный доступ к БД через `docker exec`.

| Параметр | Текущее | Рекомендуемое |
|---|---|---|
| PermitRootLogin | yes | prohibit-password / no |
| PasswordAuthentication | yes | no |
| PubkeyAuthentication | yes | yes ✅ |
| Port | 22 | ok (obscurity = minor) |
| fail2ban | not installed | installed + sshd jail |
| ufw | active, 22/2096/42240 whitelisted | ✅ |

**Отслеживается задачей `SEC-501-HOST-HARDENING`. 🔴 БЛОКЕР для live execution.**

---

## 9. Документация — ⚠️ PARTIAL

| Документ | Статус |
|---|---|
| TASK_BOARD.md | ✅ актуален |
| PROJECT_CHANGELOG.md (INFRA-002 entries) | ✅ 3 записи |
| errors-log.md (INFRA-002 lessons) | ✅ LESSON-006.x |
| 03_ARCHITECTURE_BLUEPRINT.md | ✅ существует |
| User-provisioning runbook | ❌ отсутствует (этот документ частично компенсирует) |

---

## Accepted risks

| # | Риск | Обоснование | Срок действия |
|---|---|---|---|
| 1 | `127.0.0.1/32 trust` в pg_hba | Single-root host, нет обычных пользователей | До появления multi-user на хосте |
| 2 | ssl_ciphers содержит MEDIUM+3DES | Фактически все сессии TLSv1.3/AES-256-GCM | Candidate for hardening |
| 3 | ssl_min_protocol_version TLSv1.2 | Все клиенты поддерживают TLSv1.3 | Candidate for hardening |
| 4 | `Artem15` в git history | Пароль ротирован (INFRA-002-006.0b); undo history невозможен | Постоянно |
| 5 | Startup race window firewall | <нескольких секунд, pg_hba reject компенсирует | До `firewall-startup-race-fix` |

---

## Open tasks after INFRA-002

| ID | Priority | Blocks live? |
|---|---|---|
| INFRA-002-AUDIT-ORDER-EXEC | 🟡 Medium | Yes |
| INFRA-003-BACKUP-POLICY | 🔴 High | **Yes** |
| SEC-501-HOST-HARDENING | 🔴 High | **Yes** |
| SYS-322 secrets rotation | 🔴 High | **Yes** |
| artem15-hardcode-cleanup | 🟡 Medium | Yes (перед SYS-322) |
| INCIDENT-006.1-LOGS | 🟡 Medium | No |
| postgres-logging-hardening | 🟢 Low | No |
| firewall-startup-race-fix | 🟢 Low | No |
| user-provisioning-runbook | 🟢 Low | No |

**Критичный путь до live:** SYS-322 → artem15-hardcode-cleanup → SEC-501-HOST-HARDENING → INFRA-003-BACKUP-POLICY → INFRA-002-AUDIT-ORDER-EXEC.

---

## Verification commands reference

Команды для повторной сверки baseline (read-only):

```bash
# Network
iptables -L DOCKER-USER -v -n --line-numbers
systemctl status docker-firewall-rules.service --no-pager
ss -tlnp | grep 5433

# SSL
docker exec polymarket_postgres psql -U postgres -d polymarket -c \
  "SHOW ssl; SHOW password_encryption; SELECT ssl, version, cipher FROM pg_stat_ssl JOIN pg_stat_activity USING (pid) WHERE client_addr IS NOT NULL;"

# pg_hba
docker exec polymarket_postgres psql -U postgres -d polymarket -c \
  "SELECT line_number, type, database, user_name, address, auth_method FROM pg_hba_file_rules ORDER BY line_number;"

# Roles
docker exec polymarket_postgres psql -U postgres -d polymarket -c "\du"

# Secrets
ls -la /root/polymarket-bot/.env
git -C /root/polymarket-bot log --all --full-history -- .env
```

---

## Audit log

| Date | Auditor | Result | Notes |
|---|---|---|---|
| 2026-04-11 | STRATEGY chat INFRA-002-006.2b | ⚠️ → baseline established | 9 stages, 6 new tasks created |
| 2026-04-11 | Roo (INFRA-002-008) | ⚠️ → baseline verified | 10 stages, 5 new findings |

---

*Document generated as part of INFRA-002-008 completion. Maintained by STRATEGY.*