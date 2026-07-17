#!/bin/bash
# ACT-003: daily fetch — account_activity + account_positions_snapshot
# Runs both fetch scripts sequentially under a single flock to prevent
# overlapping runs if a previous invocation is still paginating the API.

set -e

# Load environment variables from .env (PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD)
set -a
source /root/polymarket-bot/.env
set +a

LOG_PREFIX="[account_activity_fetch]"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "$LOG_PREFIX $TIMESTAMP — START"

cd /root/polymarket-bot

echo "$LOG_PREFIX Step 1: fetch_account_activity.py"
python3 scripts/fetch_account_activity.py

echo "$LOG_PREFIX Step 2: fetch_account_positions_snapshot.py"
python3 scripts/fetch_account_positions_snapshot.py

echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') — DONE"
