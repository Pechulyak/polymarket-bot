#!/bin/bash
# FARM-022: farm_screen cron — запуск 2×/день (09:00, 21:00)
# Записывает результаты в farming_market_candidates
# Cron: 0 9,21 * * * cd /root/polymarket-bot && FARM_SCREEN_DB_WRITE=true ./scripts/run_farm_screen.sh >> logs/farm_screen_cron.log 2>&1

set -e

# Load environment
set -a
source /root/polymarket-bot/.env
set +a

LOG_PREFIX="[farm_screen]"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "$LOG_PREFIX $TIMESTAMP — START"

# DB write enabled via env
export FARM_SCREEN_DB_WRITE=true

cd /root/polymarket-bot

# OUR_SIZE configurable через argv[1], default 300 (positional arg)
OUR_SIZE="${1:-300}"

python3 farming/tools/farm_screen.py "$OUR_SIZE"

echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') — DONE"
