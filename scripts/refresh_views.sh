#!/bin/bash
#
# Phase 4: Refresh materialized views
# Runs after settlement cron (15 minutes after every even hour)
# Views use CONCURRENTLY — не блокируют SELECT во время refresh
#

set -e

LOG_FILE="/var/log/polymarket/view_refresh.log"
DB_CMD="docker exec polymarket_postgres psql -U postgres -d polymarket -c"

echo "$(date '+%Y-%m-%d %H:%M:%S'): Starting view refresh..." >> "$LOG_FILE"

# Refresh в порядке зависимостей (whale_pnl_summary не зависит от остальных)
$DB_CMD "REFRESH MATERIALIZED VIEW CONCURRENTLY whale_pnl_summary;" 2>> "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S'): whale_pnl_summary refreshed" >> "$LOG_FILE"

$DB_CMD "REFRESH MATERIALIZED VIEW CONCURRENTLY paper_portfolio_state;" 2>> "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S'): paper_portfolio_state refreshed" >> "$LOG_FILE"

$DB_CMD "REFRESH MATERIALIZED VIEW CONCURRENTLY paper_simulation_pnl;" 2>> "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S'): paper_simulation_pnl refreshed" >> "$LOG_FILE"

echo "$(date '+%Y-%m-%d %H:%M:%S'): All views refreshed OK" >> "$LOG_FILE"