#!/bin/bash
# INFRA-030 / A6 — retention_whale_trades cron
# Runs daily at 04:00 via cron

set -e

# Load environment variables from .env
set -a
source /root/polymarket-bot/.env
set +a

LOG_PREFIX="[run_retention]"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "$LOG_PREFIX $TIMESTAMP — START"

RETENTION_RESULT=$(docker exec polymarket_postgres psql -U postgres -d polymarket -t -A -c "CALL retention_whale_trades(30, 10000);")

echo "$LOG_PREFIX $TIMESTAMP — DONE (result: $RETENTION_RESULT)"