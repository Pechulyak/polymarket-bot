#!/bin/bash
# TRD-443 / TASK 3-A: Staging dry-run close sell
# Target: staging postgres (host:5435)
# Uses sentinel_method=MANUAL_RUN_TRD443 for dry-run isolation

set -e

LOG_PREFIX="[run_close_sell_staging]"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_FILE="/root/polymarket-bot/logs/close_sell_staging_$(date +%Y%m%d_%H%M%S).log"

echo "$LOG_PREFIX $TIMESTAMP — START" | tee -a "$LOG_FILE"

cd /root/polymarket-bot

# Staging database URL - hardcoded to avoid any prod accidents
# Port 5435 = staging, NOT 5433 (prod)
DATABASE_URL="postgresql://postgres:KODJBlNSYhgWtVrVX3V43YvgVzY6PMpQ@localhost:5435/polymarket" \
    python3 -m src.strategy.roundtrip_builder --close --sentinel-method=MANUAL_RUN_TRD443 >> "$LOG_FILE" 2>&1

EXIT_CODE=$?
TIMESTAMP_END=$(date '+%Y-%m-%d %H:%M:%S')

if [ $EXIT_CODE -eq 0 ]; then
    echo "$LOG_PREFIX $TIMESTAMP_END — DONE (exit 0)" | tee -a "$LOG_FILE"
else
    echo "$LOG_PREFIX $TIMESTAMP_END — FAILED (exit $EXIT_CODE)" | tee -a "$LOG_FILE"
    exit $EXIT_CODE
fi