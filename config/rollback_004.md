# ROLLBACK для INFRA-002-004

Если применение нового pg_hba.conf сломает систему:

```bash
# 1. Вернуть бэкап pg_hba.conf в контейнер
docker cp ~/polymarket-bot/baseline_20260407_184145/baseline_pg_hba_20260407_183652.conf polymarket_postgres:/var/lib/postgresql/data/pg_hba.conf

# 2. Reload (не рестарт)
docker exec polymarket_postgres psql -U postgres -c "SELECT pg_reload_conf();"

# 3. Проверка
docker exec polymarket_postgres psql -U postgres -c "SELECT 1;"

# 4. smoke_test
cd ~/polymarket-bot && bash scripts/smoke_test.sh
```

Ожидаемый результат rollback: 23/23 PASS как в baseline.

## Ключевые отличия от baseline:

| Параметр | Baseline | New |
|----------|----------|-----|
| 0.0.0.0/0 | trust | reject |
| ::0/0 | trust | reject |
| Docker network | (none) | 172.18.0.0/16 trust |
| grafana_reader | (none) | 62.60.233.100/32 scram-sha-256 |
| order_executor | (none) | 62.60.233.100/32 scram-sha-256 |
| replication | trust | (removed - не нужен)