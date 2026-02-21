#!/bin/bash
# Polymarket Bot - Deployment Script
# Usage: ./scripts/deploy.sh [production|staging]

set -e

ENV=${1:-production}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="logs/deploy_$TIMESTAMP.log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARN:${NC} $1" | tee -a "$LOG_FILE"
}

log "Starting deployment (ENV: $ENV)"

# Check if .env exists
if [ ! -f .env ]; then
    error ".env file not found!"
    exit 1
fi

# Backup current state
log "Creating backup..."
if [ -d .git ]; then
    git tag "deploy_$TIMESTAMP" || true
fi

# Pull latest code
log "Pulling latest code..."
git pull origin main

# Pull latest Docker images
log "Pulling latest Docker images..."
docker-compose pull

# Build and start containers
log "Building and starting containers..."
docker-compose up -d --build

# Wait for services
log "Waiting for services to be ready..."
sleep 10

# Health check
log "Performing health check..."

# Check PostgreSQL
if docker-compose exec -T postgres pg_isready -U postgres; then
    log "PostgreSQL: OK"
else
    error "PostgreSQL: FAILED"
    exit 1
fi

# Check Redis
if docker-compose exec -T redis redis-cli ping | grep -q PONG; then
    log "Redis: OK"
else
    error "Redis: FAILED"
    exit 1
fi

# Check Bot
if docker-compose ps bot | grep -q "Up"; then
    log "Bot: OK"
else
    error "Bot: FAILED"
    docker-compose logs bot
    exit 1
fi

# Show status
log "Deployment completed successfully!"
docker-compose ps

# Cleanup old images
log "Cleaning up old Docker images..."
docker image prune -f

log "Deployment finished at $(date)"
