#!/bin/bash
# Polymarket Backup Restore Test (INFRA-003)
# Downloads latest backup from B2, restores to test DB, validates, cleans up

set -euo pipefail

# Configuration
BACKUP_DIR="/var/backups/polymarket"
LOG_FILE="/var/log/polymarket/backup.log"
B2_REMOTE="b2-polymarket"
B2_PATH="polymarket-backups/daily"
DOCKER_CONTAINER="polymarket_postgres"
TEST_DB="polymarket_restore_test"

# Timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

error_exit() {
    log "RESTORE ERROR: $1"
    exit 1
}

# Load only BACKUP_GPG_PASSPHRASE
if [[ -f .env ]]; then
    BACKUP_GPG_PASSPHRASE=$(grep "^BACKUP_GPG_PASSPHRASE=" .env | cut -d'=' -f2-)
fi

if [[ -z "${BACKUP_GPG_PASSPHRASE:-}" ]]; then
    error_exit "BACKUP_GPG_PASSPHRASE not set in .env"
fi

mkdir -p "$BACKUP_DIR"

log "Starting restore test..."

# Find latest backup in B2
log "Finding latest backup in B2..."
LATEST=$(rclone lsf "$B2_REMOTE:$B2_PATH/" --files-only 2>/dev/null | sort | tail -1 || true)

if [[ -z "$LATEST" ]]; then
    error_exit "No backup found in B2"
fi

log "Latest backup: $LATEST"

# Download latest backup
log "Downloading latest backup..."
rclone copy "$B2_REMOTE:$B2_PATH/$LATEST" "$BACKUP_DIR/" || error_exit "Failed to download backup"

ENCRYPTED_FILE="$BACKUP_DIR/$LATEST"
DUMP_FILE="${ENCRYPTED_FILE%.gpg}"

if [[ ! -f "$ENCRYPTED_FILE" ]]; then
    error_exit "Downloaded file not found"
fi

# Decrypt
log "Decrypting backup..."
echo "$BACKUP_GPG_PASSPHRASE" | gpg --batch --yes --decrypt \
    --passphrase-fd 0 \
    --output="$DUMP_FILE" \
    "$ENCRYPTED_FILE" || error_exit "GPG decryption failed"

if [[ ! -f "$DUMP_FILE" ]]; then
    error_exit "Decrypted dump not found"
fi

log "Decrypted: $(ls -lh "$DUMP_FILE" | awk '{print $5}')"

# Get baseline counts
log "Getting baseline counts from source DB..."
SOURCE_TABLES=$(docker exec "$DOCKER_CONTAINER" psql -U postgres -d polymarket -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" | xargs)
SOURCE_ROUNDS=$(docker exec "$DOCKER_CONTAINER" psql -U postgres -d polymarket -t -c "SELECT COUNT(*) FROM whale_trade_roundtrips;" | xargs)

log "Source DB: tables=$SOURCE_TABLES, roundtrips=$SOURCE_ROUNDS"

# Drop test DB if exists
log "Creating test database $TEST_DB..."
docker exec "$DOCKER_CONTAINER" psql -U postgres -c "DROP DATABASE IF EXISTS $TEST_DB;" 2>/dev/null || true
docker exec "$DOCKER_CONTAINER" psql -U postgres -c "CREATE DATABASE $TEST_DB;"

# Restore to test DB
log "Restoring to $TEST_DB..."
docker exec -i "$DOCKER_CONTAINER" pg_restore -U postgres -d "$TEST_DB" < "$DUMP_FILE" || error_exit "pg_restore failed"

# Verify counts
log "Verifying restored database..."
RESTORED_TABLES=$(docker exec "$DOCKER_CONTAINER" psql -U postgres -d "$TEST_DB" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" | xargs)
RESTORED_ROUNDS=$(docker exec "$DOCKER_CONTAINER" psql -U postgres -d "$TEST_DB" -t -c "SELECT COUNT(*) FROM whale_trade_roundtrips;" | xargs)

log "Restored DB: tables=$RESTORED_TABLES, roundtrips=$RESTORED_ROUNDS"

# Compare
if [[ "$SOURCE_TABLES" != "$RESTORED_TABLES" ]]; then
    error_exit "Table count mismatch: source=$SOURCE_TABLES, restored=$RESTORED_TABLES"
fi

if [[ "$SOURCE_ROUNDS" != "$RESTORED_ROUNDS" ]]; then
    error_exit "Roundtrip count mismatch: source=$SOURCE_ROUNDS, restored=$RESTORED_ROUNDS"
fi

log "Validation passed!"

# Cleanup test DB
log "Cleaning up test database..."
docker exec "$DOCKER_CONTAINER" psql -U postgres -c "DROP DATABASE IF EXISTS $TEST_DB;" || true

# Cleanup local files
log "Cleaning up local files..."
rm -f "$ENCRYPTED_FILE" "$DUMP_FILE" || error_exit "Failed to cleanup local files"

if [[ -f "$ENCRYPTED_FILE" ]] || [[ -f "$DUMP_FILE" ]]; then
    error_exit "Local files not fully cleaned up"
fi

log "Restore test completed successfully!"
log "---"

exit 0