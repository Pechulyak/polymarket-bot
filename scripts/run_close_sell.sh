#!/bin/bash
# TRD-443 / Close Sell pipeline wrapper
# Runs via cron: python3 -m src.strategy.roundtrip_builder --close
# This is the PRODUCTION template - do NOT run during TASK 3-A

set -e

# Load environment variables from .env
set -a
source /root/polymarket-bot/.env
set +a

LOG_PREFIX="[run_close_sell]"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_FILE="/root/polymarket-bot/logs/close_sell_cron.log"

echo "$LOG_PREFIX $TIMESTAMP — START" | tee -a "$LOG_FILE"

cd /root/polymarket-bot

# Run close positions
python3 -m src.strategy.roundtrip_builder --close >> "$LOG_FILE" 2>&1

EXIT_CODE=$?
TIMESTAMP_END=$(date '+%Y-%m-%d %H:%M:%S')

if [ $EXIT_CODE -eq 0 ]; then
    echo "$LOG_PREFIX $TIMESTAMP_END — DONE (exit 0)" | tee -a "$LOG_FILE"
else
    echo "$LOG_PREFIX $TIMESTAMP_END — FAILED (exit $EXIT_CODE)" | tee -a "$LOG_FILE"
    exit $EXIT_CODE
fi