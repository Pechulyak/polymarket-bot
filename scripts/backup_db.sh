#!/bin/bash
# Polymarket Database Backup Script (INFRA-003)
# pg_dump + GPG encryption + Backblaze B2 upload + retention

set -euo pipefail

# Configuration
BACKUP_DIR="/var/backups/polymarket"
LOG_FILE="/var/log/polymarket/backup.log"
B2_REMOTE="b2-polymarket"
B2_PATH="polymarket-backups/daily"
RETENTION_DAYS=7
DOCKER_CONTAINER="polymarket_postgres"

# Detect script directory for reliable path resolution (INFRA-034)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALERT_ENV="$SCRIPT_DIR/../.alert_env"
MAIN_ENV="$SCRIPT_DIR/../.env"

# Timestamp for log
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

error_exit() {
    log "ERROR: $1"
    send_telegram_alert "🔴 BACKUP FAILED: polymarket_bot - $1"
    exit 1
}

# Telegram notification function
send_telegram_alert() {
    local message="$1"
    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]] || [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
        log "Telegram not configured - skipping alert"
        return
    fi
    local url="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
    local data="chat_id=${TELEGRAM_CHAT_ID}&text=${message}&parse_mode=HTML"
    curl -s -X POST "$url" -d "$data" --max-time 30 || log "Telegram alert failed"
}

# Load .alert_env FIRST as emergency bus (INFRA-034)
# This ensures Telegram alerts work even if main .env fails to load
if [[ -f "$ALERT_ENV" ]]; then
    TELEGRAM_BOT_TOKEN=$(grep "^TELEGRAM_ALERT_BOT_TOKEN=" "$ALERT_ENV" | cut -d'=' -f2-)
    TELEGRAM_CHAT_ID=$(grep "^TELEGRAM_CHAT_ID=" "$ALERT_ENV" | cut -d'=' -f2-)
fi

# Load main .env (absolute path) — overrides alert_env for telegram if values present
if [[ -f "$MAIN_ENV" ]]; then
    BACKUP_GPG_PASSPHRASE=$(grep "^BACKUP_GPG_PASSPHRASE=" "$MAIN_ENV" | cut -d'=' -f2-)
    # Override Telegram only if .env has non-empty value
    tg_token=$(grep "^TELEGRAM_ALERT_BOT_TOKEN=" "$MAIN_ENV" | cut -d'=' -f2-)
    tg_chat=$(grep "^TELEGRAM_CHAT_ID=" "$MAIN_ENV" | cut -d'=' -f2-)
    [[ -n "$tg_token" ]] && TELEGRAM_BOT_TOKEN="$tg_token" || true
    [[ -n "$tg_chat" ]] && TELEGRAM_CHAT_ID="$tg_chat" || true
fi

# Validate GPG passphrase
if [[ -z "${BACKUP_GPG_PASSPHRASE:-}" ]]; then
    error_exit "BACKUP_GPG_PASSPHRASE not set in $MAIN_ENV"
fi

# Create directories
log "Creating backup directory..."
mkdir -p "$BACKUP_DIR" || error_exit "Failed to create $BACKUP_DIR"
mkdir -p "$(dirname "$LOG_FILE")" || error_exit "Failed to create log directory"

# Generate timestamp for filename
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
DUMP_FILE="$BACKUP_DIR/polymarket_${TIMESTAMP}.dump"
ENCRYPTED_FILE="${DUMP_FILE}.gpg"

log "Starting backup process..."

# pg_dump via docker exec
log "Running pg_dump..."
docker exec "$DOCKER_CONTAINER" pg_dump -U postgres -d polymarket \
    --format=custom \
    --compress=9 \
    --file="$DUMP_FILE" 2>/dev/null || {
    # Fallback: pg_dump on host connecting via docker
    docker exec "$DOCKER_CONTAINER" sh -c "
        pg_dump -U postgres -d polymarket --format=custom --compress=9" > "$DUMP_FILE"
}

if [[ ! -f "$DUMP_FILE" ]]; then
    error_exit "pg_dump failed - dump file not created"
fi

log "Dump file created: $(ls -lh "$DUMP_FILE" | awk '{print $5}')"

# GPG encryption
log "Encrypting with GPG..."
echo "$BACKUP_GPG_PASSPHRASE" | gpg --batch --yes --symmetric \
    --cipher-algo AES256 \
    --passphrase-fd 0 \
    --output="$ENCRYPTED_FILE" \
    "$DUMP_FILE" || error_exit "GPG encryption failed"

log "Encrypted file created: $(ls -lh "$ENCRYPTED_FILE" | awk '{print $5}')"

# Remove unencrypted dump
log "Removing unencrypted dump..."
rm -f "$DUMP_FILE" || error_exit "Failed to remove unencrypted dump"

# Verify removal
if [[ -f "$DUMP_FILE" ]]; then
    error_exit "Unencrypted dump still exists after removal"
fi

# Upload to Backblaze B2
log "Uploading to Backblaze B2..."
rclone copy "$ENCRYPTED_FILE" "$B2_REMOTE:$B2_PATH/" || error_exit "rclone upload failed"

log "Uploaded to $B2_REMOTE:$B2_PATH/"

# Remove local encrypted file
log "Removing local encrypted file..."
rm -f "$ENCRYPTED_FILE" || error_exit "Failed to remove local encrypted file"

# Retention: delete old backups from B2
log "Running retention policy (delete files older than $RETENTION_DAYS days)..."
rclone delete "$B2_REMOTE:$B2_PATH/" --min-age ${RETENTION_DAYS}d 2>/dev/null || true

log "Backup completed successfully!"
DUMP_SIZE=$(rclone ls "$B2_REMOTE:$B2_PATH/polymarket_${TIMESTAMP}.dump.gpg" 2>/dev/null | awk '{print $1}' || echo "unknown")
if [[ -z "$DUMP_SIZE" || "$DUMP_SIZE" == "unknown" ]]; then
    send_telegram_alert "⚠️ BACKUP UPLOADED but SIZE UNKNOWN - verify B2 - $(date '+%Y-%m-%d')"
else
    send_telegram_alert "🟢 BACKUP OK: polymarket_bot - $(date '+%Y-%m-%d') - ${DUMP_SIZE}b"
fi
log "---"

exit 0
