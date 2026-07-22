#!/bin/bash
# DATA-413 — daily rebuild of account_daily_position_ledger (ADPL).
# Runs at 10:00 UTC, after account_activity fetch (04:10 UTC) and the S2
# farming snapshot (~09:35 UTC) have landed D-1 data. Full idempotent
# rebuild (TRUNCATE + INSERT); source tables are small.

set -e

# Load environment variables from .env (PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD)
set -a
source /root/polymarket-bot/.env
set +a

LOG_PREFIX="[run_build_ledger]"
echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') — START"

cd /root/polymarket-bot
python3 scripts/build_account_daily_ledger.py

echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') — DONE"
