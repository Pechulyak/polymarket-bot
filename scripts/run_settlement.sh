#!/bin/bash
# PHASE3-006: SQL-based settlement pipeline
# Runs every 2 hours via cron
# Replaces: roundtrip_builder --settle

set -e

# Load environment variables from .env
set -a
source /root/polymarket-bot/.env
set +a

LOG_PREFIX="[run_settlement]"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "$LOG_PREFIX $TIMESTAMP — START"

# Step 1: Fetch market resolutions from CLOB API
echo "$LOG_PREFIX Step 1: Fetching market resolutions..."
cd /root/polymarket-bot
python3 scripts/fetch_market_resolutions.py
FETCH_EXIT=$?

if [ $FETCH_EXIT -ne 0 ]; then
    echo "$LOG_PREFIX ERROR: fetch_market_resolutions.py failed with exit code $FETCH_EXIT"
    exit 1
fi

# Step 2: Run SQL settlement
echo "$LOG_PREFIX Step 2: Running SQL settlement..."
SETTLE_RESULT=$(docker exec polymarket_postgres psql -U postgres -d polymarket -t -A -c \
    "SELECT * FROM settle_resolved_positions();")

echo "$LOG_PREFIX Settlement result: $SETTLE_RESULT"

# Step 3: Update whale P&L for affected wallets
echo "$LOG_PREFIX Step 3: Updating whale P&L..."
UPDATED=$(docker exec polymarket_postgres psql -U postgres -d polymarket -t -A -c \
    "SELECT updated_count FROM update_whale_pnl_from_roundtrips();")

echo "$LOG_PREFIX Whales updated: $UPDATED"

echo "$LOG_PREFIX $TIMESTAMP — DONE"