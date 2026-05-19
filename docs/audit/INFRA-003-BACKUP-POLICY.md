# INFRA-003 — Backup Policy

## Overview
Automated daily encrypted backups of PostgreSQL database to Backblaze B2.

## Backup Schedule

| Параметр | Значение |
|----------|----------|
| Время | 03:00 UTC daily |
| Цель | Backblaze B2: polymarket-backups/daily/ |
| Retention | 7 days |
| Encryption | GPG AES-256 |

## Manual Commands

### Run backup manually
```bash
/root/polymarket-bot/scripts/backup_db.sh
```

### Run restore test
```bash
/root/polymarket-bot/scripts/backup_restore_test.sh
```

### View logs
```bash
tail -f /var/log/polymarket/backup.log
```

### List backups in B2
```bash
rclone ls b2-polymarket:polymarket-backups/daily/
```

## Restore from Backup

### Manual restore (example)
```bash
# Download from B2
rclone copy b2-polymarket:polymarket-backups/daily/polymarket_20260412_165307.dump.gpg /tmp/

# Decrypt
gpg --decrypt --output /tmp/polymarket_20260412_165307.dump /tmp/polymarket_20260412_165307.dump.gpg

# Restore
docker exec -i polymarket_postgres pg_restore -U postgres -d polymarket < /tmp/polymarket_20260412_165307.dump
```

## Files

- `scripts/backup_db.sh` — backup script (chmod 700)
- `scripts/backup_restore_test.sh` — restore test script
- `.env` — BACKUP_GPG_PASSPHRASE (DO NOT COMMIT)

## Monitoring

- Telegram alert on failure (configured in backup_db.sh)
- Log location: `/var/log/polymarket/backup.log`

## Credentials Required

- GPG passphrase: in `.env` as `BACKUP_GPG_PASSPHRASE`
- Backblaze B2: configured in `~/.config/rclone/rclone.conf` (remote: `b2-polymarket`)

## Verify Backup Integrity

Restore test runs automatically. To manually verify:
```bash
bash /root/polymarket-bot/scripts/backup_restore_test.sh
```

Expected output:
- Tables: 16 (match source)
- whale_trade_roundtrips: count matches source DB