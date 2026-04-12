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

# Load environment variables
if [[ -f .env ]]; then
    BACKUP_GPG_PASSPHRASE=$(grep "^BACKUP_GPG_PASSPHRASE=" .env | cut -d'=' -f2-)
    TELEGRAM_BOT_TOKEN=$(grep "^TELEGRAM_ALERT_BOT_TOKEN=" .env | cut -d'=' -f2-)
    TELEGRAM_CHAT_ID=$(grep "^TELEGRAM_CHAT_ID=" .env | cut -d'=' -f2-)
fi

# Validate GPG passphrase
if [[ -z "${BACKUP_GPG_PASSPHRASE:-}" ]]; then
    error_exit "BACKUP_GPG_PASSPHRASE not set in .env"
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
log "---"

exit 0