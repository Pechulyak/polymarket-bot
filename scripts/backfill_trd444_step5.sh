#!/bin/bash
#
# backfill_trd444_step5.sh
# Purpose: Backfill close_size_usd = open_size_usd for SETTLEMENT_WIN/LOSS rows where close_size_usd IS NULL
# Target table: whale_trade_roundtrips
# Safety cap: 25 iterations max
# Exit condition: affected = 0
#

set -euo pipefail

# === CONFIGURATION ===
BATCH_SIZE="${BATCH_SIZE:-5000}"
MAX_ITERATIONS=25
BATCH_DELAY=1
LOG_DIR="/root/polymarket-bot/logs"
SCRIPT_TS=$(date '+%Y%m%d_%H%M%S')
LOG_FILE="${LOG_DIR}/trd444_step5_backfill_${SCRIPT_TS}.log"

# Ensure log directory exists
mkdir -p "${LOG_DIR}"

# === SQL TEMPLATE ===
SQL_TEMPLATE="
WITH updated AS (
    UPDATE whale_trade_roundtrips
    SET close_size_usd = open_size_usd, updated_at = NOW()
    WHERE id IN (
        SELECT id
        FROM whale_trade_roundtrips
        WHERE close_type IN ('SETTLEMENT_WIN', 'SETTLEMENT_LOSS')
          AND close_size_usd IS NULL
        LIMIT ${BATCH_SIZE}
    )
    RETURNING 1
)
SELECT count(*) FROM updated;
"

# === STATE ===
iteration=0
cumulative_total=0
start_time=$(date '+%Y-%m-%d %H:%M:%S')

# === LOG HELPER ===
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "${msg}" | tee -a "${LOG_FILE}"
}

# === MAIN ===
log "=========================================="
log "TRD-444 Step 5.2 — Backfill close_size_usd"
log "=========================================="
log "Start time:       ${start_time}"
log "Batch size:       ${BATCH_SIZE}"
log "Max iterations:   ${MAX_ITERATIONS}"
log "Log file:         ${LOG_FILE}"
log "=========================================="

while true; do
    iteration=$((iteration + 1))

    log ""
    log "--- Batch ${iteration} ---"

    # Execute single batch via docker exec (separate connection per batch)
    # Errors go to stderr naturally; || block catches non-zero exit code
    raw_output=$(docker exec polymarket_postgres psql \
        -U postgres \
        -d polymarket \
        -t -A -c "${SQL_TEMPLATE}") || {
        log "ERROR: psql exited with code $? on batch ${iteration}"
        log "Last cumulative total: ${cumulative_total}"
        exit 1
    }

    # Parse and sanitize psql output
    affected=$(echo "${raw_output}" | tr -d '[:space:]')

    # Sanity check: must be numeric or empty
    if [[ -z "${affected}" ]]; then
        affected=0
    elif ! [[ "${affected}" =~ ^[0-9]+$ ]]; then
        log "ERROR: Non-numeric output from psql: '${raw_output}'"
        log "Affected value: '${affected}'"
        exit 1
    fi

    cumulative_total=$((cumulative_total + affected))

    log "Batch number:     ${iteration}"
    log "Affected count:   ${affected}"
    log "Cumulative total: ${cumulative_total}"

    # Exit condition: no rows updated in this batch
    if [[ "${affected}" -eq 0 ]]; then
        log ""
        log "Exit condition met (affected = 0). Done."
        break
    fi

    # Safety cap check
    if [[ ${iteration} -ge ${MAX_ITERATIONS} ]]; then
        log ""
        log "ERROR: Safety cap reached (${MAX_ITERATIONS} iterations)"
        log "Cumulative total: ${cumulative_total}"
        exit 1
    fi

    # Sleep only if next iteration is possible
    sleep "${BATCH_DELAY}"
done

end_time=$(date '+%Y-%m-%d %H:%M:%S')

log ""
log "=========================================="
log "Backfill complete"
log "=========================================="
log "End time:         ${end_time}"
log "Total iterations: ${iteration}"
log "Total rows:       ${cumulative_total}"
log "=========================================="